use axum::extract::ws::{WebSocket, Message};
use serde::Serialize;
use std::sync::Arc;
use tracing::{info, warn, error};

use crate::core::reader::PltxReader;

#[derive(Serialize)]
struct SignalPayload {
    timestamp: f64,
    value: f64,
    desc: String,
    seq: u64,
    end_flag: bool,
}

pub async fn handle_ws_fetch(
    mut socket: WebSocket,
    reader: Arc<tokio::sync::Mutex<PltxReader>>,
    signal_name: String,
) {
    info!("ws_fetch streaming started: {}", signal_name);

    let mut seq: u64 = 0;

    // 🔒 Lock the reader briefly to get signal ID and read chunks
    let chunks = {
        let reader_guard = reader.lock().await;

        // Get signal ID
        let signal_id = match reader_guard.get_signal_id_by_name(&signal_name) {
            Some(id) => id,
            None => {
                error!("signal id not found: {}", signal_name);
                return;
            }
        };

        // Read all chunks at once
        match reader_guard.read_signal_chunks(signal_id) {
            Ok(chunks) => chunks,
            Err(e) => {
                error!("read_signal_chunks failed: {}", e);
                return;
            }
        }
    }; // Lock is released here

    // Iterate through chunks
    for chunk in chunks {

        // Send each point in the chunk
        for i in 0..chunk.len() {
            let payload = SignalPayload {
                timestamp: chunk.timestamps[i],
                value: chunk.values[i],
                desc: String::new(),
                seq,
                end_flag: false,
            };

            let json = match serde_json::to_string(&payload) {
                Ok(j) => j,
                Err(e) => {
                    error!("json serialize error: {}", e);
                    return;
                }
            };

            if let Err(e) = socket.send(Message::Text(json.into())).await {
                warn!("ws send failed: {}", e);
                return;
            }

            seq += 1;
        }
    }

    // 🔚 END FLAG
    let end_payload = SignalPayload {
        timestamp: 0.0,
        value: 0.0,
        desc: String::new(),
        seq,
        end_flag: true,
    };

    if let Ok(json) = serde_json::to_string(&end_payload) {
        let _ = socket.send(Message::Text(json.into())).await;
    }

    info!("ws_fetch finished: {}", signal_name);
}