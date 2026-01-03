// Example usage of PLTX reader - Updated for thread-safe API

use pltx_reader::{PltxReader, Result};
use tracing::{debug, info, Level};
use tracing_subscriber;

fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_max_level(Level::DEBUG)
        .init();

    // Open a PLTX file
    let reader = PltxReader::open("data/recording.pltx")?;

    // List all signals
    info!("Available signals:");
    for (id, name) in reader.list_signals() {
        info!("  [{}] {}", id, name);
        if let Some(meta) = reader.get_signal_metadata(id) {
            if !meta.unit.is_empty() {
                info!("      Unit: {}", meta.unit);
            }
            if !meta.description.is_empty() {
                info!("      Description: {}", meta.description);
            }
        }
    }

    // Read a specific signal by name
    if let Some(signal_id) = reader.get_signal_id_by_name("temperature") {
        info!("\nReading signal 'temperature' (ID: {})", signal_id);
        
        // Read all data at once
        let data = reader.read_signal_all(signal_id)?;
        info!("Total records: {}", data.len());
        
        if !data.is_empty() {
            info!("First record: ts={}, value={}", 
                data.timestamps[0], data.values[0]);
            info!("Last record: ts={}, value={}", 
                data.timestamps[data.len() - 1], 
                data.values[data.len() - 1]);
        }
    }

    // Read signal by ID using chunks (memory efficient)
    let signal_id = 1;
    info!("\nReading signal {} in chunks:", signal_id);
    
    let chunks = reader.read_signal_chunks(signal_id)?;
    let mut total_records = 0;
    for chunk in chunks {
        total_records += chunk.len();
        debug!("  Chunk with {} records", chunk.len());
    }
    info!("Total records in chunks: {}", total_records);

    // Read time range
    info!("\nReading time range [100.0, 200.0]:");
    let range_data = reader.read_time_range(signal_id, 100.0, 200.0)?;
    info!("Total records in range: {}", range_data.len());
    
    if !range_data.is_empty() {
        info!("First in range: ts={}, value={}", 
            range_data.timestamps[0], range_data.values[0]);
        info!("Last in range: ts={}, value={}", 
            range_data.timestamps[range_data.len() - 1], 
            range_data.values[range_data.len() - 1]);
    }

    Ok(())
}