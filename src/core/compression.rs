// Compression backend implementations

use crate::core::constants::CompressionType;
use crate::core::error::{PltxError, Result};
use flate2::read::ZlibDecoder;
use std::io::Read;

pub fn decompress(data: &[u8], compression: CompressionType) -> Result<Vec<u8>> {
    match compression {
        CompressionType::None => Ok(data.to_vec()),
        
        CompressionType::Zlib => {
            let mut decoder = ZlibDecoder::new(data);
            let mut decompressed = Vec::new();
            decoder
                .read_to_end(&mut decompressed)
                .map_err(|e| PltxError::DecompressionFailed(format!("Zlib: {}", e)))?;
            Ok(decompressed)
        }

        #[cfg(feature = "lz4")]
        CompressionType::Lz4 => {
            lz4::block::decompress(data, None)
                .map_err(|e| PltxError::DecompressionFailed(format!("LZ4: {}", e)))
        }

        #[cfg(not(feature = "lz4"))]
        CompressionType::Lz4 => {
            Err(PltxError::UnsupportedCompression(2))
        }

        #[cfg(feature = "zstd")]
        CompressionType::Zstd => {
            zstd::decode_all(data)
                .map_err(|e| PltxError::DecompressionFailed(format!("Zstd: {}", e)))
        }

        #[cfg(not(feature = "zstd"))]
        CompressionType::Zstd => {
            Err(PltxError::UnsupportedCompression(3))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_decompress_none() {
        let data = b"hello world";
        let result = decompress(data, CompressionType::None).unwrap();
        assert_eq!(result, data);
    }

    #[test]
    fn test_decompress_zlib() {
        use flate2::write::ZlibEncoder;
        use flate2::Compression;
        use std::io::Write;

        let original = b"hello world";
        let mut encoder = ZlibEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(original).unwrap();
        let compressed = encoder.finish().unwrap();

        let decompressed = decompress(&compressed, CompressionType::Zlib).unwrap();
        assert_eq!(decompressed, original);
    }
}