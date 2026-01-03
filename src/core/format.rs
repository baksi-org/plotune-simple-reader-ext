// Data structures for PLTX format

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SignalMetadata {
    pub name: String,
    pub unit: String,
    pub description: String,
    pub source: String,
}

impl SignalMetadata {
    pub fn new(name: String) -> Self {
        Self {
            name,
            unit: String::new(),
            description: String::new(),
            source: String::new(),
        }
    }
}

#[derive(Debug, Clone)]
pub struct FileHeader {
    pub version: u8,
    pub compression: u8,
    pub created: f64,
    pub signals: HashMap<u32, SignalMetadata>,
}

#[derive(Debug, Clone)]
pub struct ChunkHeader {
    pub signal_id: u32,
    pub record_count: u32,
    pub raw_length: u32,
    pub compressed_length: u32,
    pub min_timestamp: f64,
    pub max_timestamp: f64,
}

#[derive(Debug, Clone)]
pub struct IndexEntry {
    pub signal_id: u32,
    pub offset: u64,
    pub min_timestamp: f64,
    pub max_timestamp: f64,
}

#[derive(Debug, Clone)]
pub struct TimeseriesChunk {
    pub timestamps: Vec<f64>,
    pub values: Vec<f64>,
}

impl TimeseriesChunk {
    pub fn new() -> Self {
        Self {
            timestamps: Vec::new(),
            values: Vec::new(),
        }
    }

    pub fn with_capacity(cap: usize) -> Self {
        Self {
            timestamps: Vec::with_capacity(cap),
            values: Vec::with_capacity(cap),
        }
    }

    pub fn len(&self) -> usize {
        self.timestamps.len()
    }

    pub fn is_empty(&self) -> bool {
        self.timestamps.is_empty()
    }
}