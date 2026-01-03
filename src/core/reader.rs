// Main PLTX reader implementation - Thread-safe version

use crate::core::compression::decompress;
use crate::core::constants::*;
use crate::core::error::{PltxError, Result};
use crate::core::format::*;
use std::collections::HashMap;
use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

#[warn(dead_code)]
pub struct PltxReader {
    path: PathBuf,
    file: Arc<Mutex<File>>,
    header: FileHeader,
    index: HashMap<u32, Vec<IndexEntry>>,
}

impl PltxReader {
    pub fn open<P: AsRef<Path>>(path: P) -> Result<Self> {
        let path = path.as_ref().to_path_buf();
        let mut file = File::open(&path)?;

        let header = Self::read_header(&mut file)?;
        let index = Self::read_footer_and_index(&mut file)?;

        Ok(Self {
            path,
            file: Arc::new(Mutex::new(file)),
            header,
            index,
        })
    }

    fn read_header(file: &mut File) -> Result<FileHeader> {
        // Read header prefix
        let mut prefix = [0u8; HEADER_PREFIX_SIZE];
        file.read_exact(&mut prefix)?;

        // Parse prefix
        let magic = &prefix[0..4];
        if magic != MAGIC {
            return Err(PltxError::InvalidMagic {
                expected: MAGIC.to_vec(),
                got: magic.to_vec(),
            });
        }

        let version = prefix[4];
        let compression = prefix[5];
        let created = f64::from_le_bytes(prefix[6..14].try_into().unwrap());
        let sig_count = u16::from_le_bytes(prefix[14..16].try_into().unwrap());

        // Read signal metadata
        let mut signals = HashMap::new();
        for _ in 0..sig_count {
            let mut sid_buf = [0u8; 4];
            file.read_exact(&mut sid_buf)?;
            let signal_id = u32::from_le_bytes(sid_buf);

            let name = Self::read_string(file)?;
            let unit = Self::read_string(file)?;
            let description = Self::read_string(file)?;
            let source = Self::read_string(file)?;

            signals.insert(
                signal_id,
                SignalMetadata {
                    name,
                    unit,
                    description,
                    source,
                },
            );
        }

        Ok(FileHeader {
            version,
            compression,
            created,
            signals,
        })
    }

    fn read_string(file: &mut File) -> Result<String> {
        let mut len_buf = [0u8; 2];
        file.read_exact(&mut len_buf)?;
        let len = u16::from_le_bytes(len_buf) as usize;

        let mut str_buf = vec![0u8; len];
        file.read_exact(&mut str_buf)?;

        String::from_utf8(str_buf).map_err(|e| e.into())
    }

    fn read_footer_and_index(file: &mut File) -> Result<HashMap<u32, Vec<IndexEntry>>> {
        // Seek to footer
        file.seek(SeekFrom::End(-(FOOTER_SIZE as i64)))?;

        let mut footer = [0u8; FOOTER_SIZE];
        file.read_exact(&mut footer)?;

        let footer_magic = &footer[0..4];
        if footer_magic != FOOTER_MAGIC {
            return Err(PltxError::InvalidMagic {
                expected: FOOTER_MAGIC.to_vec(),
                got: footer_magic.to_vec(),
            });
        }

        let index_offset = u64::from_le_bytes(footer[4..12].try_into().unwrap());

        // Seek to index
        file.seek(SeekFrom::Start(index_offset))?;

        let mut index_magic = [0u8; 4];
        file.read_exact(&mut index_magic)?;
        if &index_magic != INDEX_MAGIC {
            return Err(PltxError::InvalidMagic {
                expected: INDEX_MAGIC.to_vec(),
                got: index_magic.to_vec(),
            });
        }

        let mut count_buf = [0u8; 4];
        file.read_exact(&mut count_buf)?;
        let entry_count = u32::from_le_bytes(count_buf);

        let mut index: HashMap<u32, Vec<IndexEntry>> = HashMap::new();
        for _ in 0..entry_count {
            let mut entry_buf = [0u8; INDEX_ENTRY_SIZE];
            file.read_exact(&mut entry_buf)?;

            let signal_id = u32::from_le_bytes(entry_buf[0..4].try_into().unwrap());
            let offset = u64::from_le_bytes(entry_buf[4..12].try_into().unwrap());
            let min_ts = f64::from_le_bytes(entry_buf[12..20].try_into().unwrap());
            let max_ts = f64::from_le_bytes(entry_buf[20..28].try_into().unwrap());

            index.entry(signal_id).or_insert_with(Vec::new).push(IndexEntry {
                signal_id,
                offset,
                min_timestamp: min_ts,
                max_timestamp: max_ts,
            });
        }

        Ok(index)
    }

    pub fn list_signals(&self) -> Vec<(u32, &str)> {
        let mut signals: Vec<_> = self
            .header
            .signals
            .iter()
            .map(|(id, meta)| (*id, meta.name.as_str()))
            .collect();
        signals.sort_by_key(|(id, _)| *id);
        signals
    }

    pub fn get_signal_metadata(&self, signal_id: u32) -> Option<&SignalMetadata> {
        self.header.signals.get(&signal_id)
    }

    pub fn get_signal_id_by_name(&self, name: &str) -> Option<u32> {
        self.header
            .signals
            .iter()
            .find(|(_, meta)| meta.name == name)
            .map(|(id, _)| *id)
    }

    pub fn read_signal_all(&self, signal_id: u32) -> Result<TimeseriesChunk> {
        let entries = self
            .index
            .get(&signal_id)
            .ok_or_else(|| PltxError::SignalNotFound(signal_id.to_string()))?;

        let compression = CompressionType::from_u8(self.header.compression)
            .ok_or(PltxError::UnsupportedCompression(self.header.compression))?;

        let mut result = TimeseriesChunk::new();

        for entry in entries {
            let chunk = self.read_chunk_at(entry.offset, compression)?;
            result.timestamps.extend(chunk.timestamps);
            result.values.extend(chunk.values);
        }

        Ok(result)
    }

    pub fn read_signal_chunks(&self, signal_id: u32) -> Result<Vec<TimeseriesChunk>> {
        let entries = self
            .index
            .get(&signal_id)
            .ok_or_else(|| PltxError::SignalNotFound(signal_id.to_string()))?;

        let compression = CompressionType::from_u8(self.header.compression)
            .ok_or(PltxError::UnsupportedCompression(self.header.compression))?;

        let mut chunks = Vec::new();

        for entry in entries {
            let chunk = self.read_chunk_at(entry.offset, compression)?;
            chunks.push(chunk);
        }

        Ok(chunks)
    }

    pub fn read_time_range(
        &self,
        signal_id: u32,
        start_time: f64,
        end_time: f64,
    ) -> Result<TimeseriesChunk> {
        let entries = self
            .index
            .get(&signal_id)
            .ok_or_else(|| PltxError::SignalNotFound(signal_id.to_string()))?;

        let compression = CompressionType::from_u8(self.header.compression)
            .ok_or(PltxError::UnsupportedCompression(self.header.compression))?;

        let mut result = TimeseriesChunk::new();

        for entry in entries {
            // Skip chunks outside time range
            if entry.max_timestamp < start_time || entry.min_timestamp > end_time {
                continue;
            }

            let chunk = self.read_chunk_at(entry.offset, compression)?;

            // Filter records within time range
            for (ts, val) in chunk.timestamps.iter().zip(chunk.values.iter()) {
                if *ts >= start_time && *ts <= end_time {
                    result.timestamps.push(*ts);
                    result.values.push(*val);
                }
            }
        }

        Ok(result)
    }

    fn read_chunk_at(&self, offset: u64, compression: CompressionType) -> Result<TimeseriesChunk> {
        let mut file = self.file.lock().unwrap();
        
        file.seek(SeekFrom::Start(offset))?;

        let mut chunk_magic = [0u8; 4];
        file.read_exact(&mut chunk_magic)?;
        if &chunk_magic != CHUNK_MAGIC {
            return Err(PltxError::CorruptedData(
                "Invalid chunk magic".to_string(),
            ));
        }

        let mut header_buf = [0u8; CHUNK_HEADER_SIZE];
        file.read_exact(&mut header_buf)?;

        let _signal_id = u32::from_le_bytes(header_buf[0..4].try_into().unwrap());
        let record_count = u32::from_le_bytes(header_buf[4..8].try_into().unwrap());
        let raw_length = u32::from_le_bytes(header_buf[8..12].try_into().unwrap());
        let compressed_length = u32::from_le_bytes(header_buf[12..16].try_into().unwrap());

        let mut compressed_data = vec![0u8; compressed_length as usize];
        file.read_exact(&mut compressed_data)?;

        let raw_data = decompress(&compressed_data, compression)?;

        if raw_data.len() != raw_length as usize {
            return Err(PltxError::CorruptedData(format!(
                "Expected {} bytes, got {}",
                raw_length,
                raw_data.len()
            )));
        }

        let mut chunk = TimeseriesChunk::with_capacity(record_count as usize);

        for i in 0..record_count as usize {
            let offset = i * RECORD_SIZE;
            let ts = f64::from_le_bytes(raw_data[offset..offset + 8].try_into().unwrap());
            let val = f64::from_le_bytes(raw_data[offset + 8..offset + 16].try_into().unwrap());
            chunk.timestamps.push(ts);
            chunk.values.push(val);
        }

        Ok(chunk)
    }
}

// Make PltxReader thread-safe
unsafe impl Send for PltxReader {}
unsafe impl Sync for PltxReader {}