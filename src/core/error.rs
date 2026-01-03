// Error handling for PLTX reader

use thiserror::Error;

pub type Result<T> = std::result::Result<T, PltxError>;

#[derive(Error, Debug)]
pub enum PltxError {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("Invalid magic bytes: expected {expected:?}, got {got:?}")]
    InvalidMagic { expected: Vec<u8>, got: Vec<u8> },

    #[error("Unsupported version: {0}")]
    UnsupportedVersion(u8),

    #[error("Unsupported compression type: {0}")]
    UnsupportedCompression(u8),

    #[error("Decompression failed: {0}")]
    DecompressionFailed(String),

    #[error("Corrupted data: {0}")]
    CorruptedData(String),

    #[error("Signal not found: {0}")]
    SignalNotFound(String),

    #[error("Invalid UTF-8 string")]
    InvalidUtf8(#[from] std::string::FromUtf8Error),

    #[error("Parse error: {0}")]
    ParseError(String),
}