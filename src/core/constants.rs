// Format constants for PLTX v2

pub const MAGIC: &[u8; 4] = b"PLTX";
pub const CHUNK_MAGIC: &[u8; 4] = b"CHNK";
pub const INDEX_MAGIC: &[u8; 4] = b"IDXT";
pub const FOOTER_MAGIC: &[u8; 4] = b"FTER";

// Compression codes
#[repr(u8)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CompressionType {
    None = 0,
    Zlib = 1,
    Lz4 = 2,
    Zstd = 3,
}

impl CompressionType {
    pub fn from_u8(val: u8) -> Option<Self> {
        match val {
            0 => Some(CompressionType::None),
            1 => Some(CompressionType::Zlib),
            2 => Some(CompressionType::Lz4),
            3 => Some(CompressionType::Zstd),
            _ => None,
        }
    }
}

// Record format: (timestamp: f64, value: f64)
pub const RECORD_SIZE: usize = 16; // 8 + 8 bytes

// Chunk header: signal_id(u32) n(u32) raw_len(u32) comp_len(u32) min_ts(f64) max_ts(f64)
pub const CHUNK_HEADER_SIZE: usize = 4 + 4 + 4 + 4 + 8 + 8; // 32 bytes

// File header prefix: MAGIC(4) version(u8) comp(u8) created(f64) sig_count(u16)
pub const HEADER_PREFIX_SIZE: usize = 4 + 1 + 1 + 8 + 2; // 16 bytes

// Index entry: sid(u32) offset(u64) min_ts(f64) max_ts(f64)
pub const INDEX_ENTRY_SIZE: usize = 4 + 8 + 8 + 8; // 28 bytes

// Footer: FOOTER_MAGIC(4) index_offset(u64)
pub const FOOTER_SIZE: usize = 4 + 8; // 12 bytes