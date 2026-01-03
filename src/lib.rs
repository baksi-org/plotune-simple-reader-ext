// PLTX v2 Rust Reader
// Main library entry point

pub mod core;

// Re-export main types
pub use core::error::{PltxError, Result};
pub use core::reader::PltxReader;
pub use core::format::{SignalMetadata, IndexEntry};
pub use core::data_handle::{handle_ws_fetch};

#[cfg(test)]
mod tests {
    #[test]
    fn test_constants() {
        use crate::core::constants::*;
        assert_eq!(MAGIC, b"PLTX");
        assert_eq!(CHUNK_MAGIC, b"CHNK");
    }
}