use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::{RwLock, Mutex};

use pltx_reader::PltxReader;

#[derive(Clone)]
pub struct SignalInfo {
    pub reader: Arc<Mutex<PltxReader>>,
    pub original_name: String,  // The actual signal name in the file
}

#[derive(Clone)]
pub struct AppState {
    // Maps unique_name -> SignalInfo (with reader and original name)
    pub signals: Arc<RwLock<HashMap<String, SignalInfo>>>,
}

impl AppState {
    pub fn new() -> Self {
        Self {
            signals: Arc::new(RwLock::new(HashMap::new())),
        }
    }
}

impl Default for AppState {
    fn default() -> Self {
        Self::new()
    }
}