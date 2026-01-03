use axum::{
    routing::{get, post},
    Router,
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
    extract::{
        Path,
        State,
        ws::WebSocketUpgrade,
    },
};

use std::sync::Arc;

use tracing::{info, debug, error};
use serde::{Serialize, Deserialize};

use crate::state::app_state::AppState;
use pltx_reader::PltxReader;

use crate::routes::ws_handler::handle_ws_fetch;
use std::collections::HashMap;

#[derive(Serialize)]
pub struct ReaderSummary {
    pub id: String,            // hex pointer id
    pub signals_count: usize,  // number of signals registered for this reader
    pub headers: Vec<String>,  // unique header list (original names)
}

/// Response for GET /readers/{id}/headers
#[derive(Serialize)]
pub struct ReaderHeaders {
    pub id: String,
    pub headers: Vec<String>,
}

#[derive(Deserialize, Debug)]
pub struct FileReadRequest {
    pub mode: String, // "online" | "offline"
    pub path: String,
}

#[derive(Serialize, Debug)]
pub struct FileReadResponse {
    pub id: String,
    pub name: String,
    pub path: String,
    pub source: String,
    pub headers: Option<Vec<String>>,
    pub desc: Option<String>,
    pub tags: Option<Vec<String>>,
    pub created_at: Option<String>,
    pub source_url: Option<String>,
}


/// =======================
/// ROUTER
/// =======================

pub fn data_routes(state: AppState) -> Router {
    Router::new()
        .route("/read-file", post(read_file))
        .route("/fetch/{:signal}", get(ws_fetch))
        .route("/readers", get(list_readers))
        .route("/readers/{:id}/headers", get(reader_headers))
        .with_state(state)
}


/// =======================
/// HANDLERS
/// =======================

async fn read_file(
    State(state): State<AppState>,
    Json(request): Json<FileReadRequest>,
) -> Response {
    debug!("Reading file: mode={}, path={}", request.mode, request.path);

    // Open reader ONCE and wrap in Arc<Mutex>
    let reader = match PltxReader::open(&request.path) {
        Ok(r) => Arc::new(tokio::sync::Mutex::new(r)),
        Err(e) => {
            error!("Failed to open file {}: {}", request.path, e);
            return StatusCode::INTERNAL_SERVER_ERROR.into_response();
        }
    };

    let mut exposed_headers = Vec::new();
    let mut signals = state.signals.write().await;

    // 🔒 Lock the reader to get signal list
    // Convert &str to String to own the data
    let signal_list: Vec<(u32, String)> = {
        let reader_guard = reader.lock().await;
        reader_guard.list_signals()
            .into_iter()
            .map(|(id, name)| (id, name.to_string()))
            .collect()
    }; // Lock released here

    // Iterate through signal names
    for (_id, name) in signal_list {
        let base_name = name;  // Already a String now
        let mut final_name = base_name.clone();

        // 👇 GLOBAL UNIQUE NAME
        if signals.contains_key(&final_name) {
            let mut i = 1;
            loop {
                let candidate = format!("{}_{}", base_name, i);
                if !signals.contains_key(&candidate) {
                    final_name = candidate;
                    break;
                }
                i += 1;
            }
        }

        info!("Register signal: {} (original: {})", final_name, base_name);

        // Store the SignalInfo with both reader and original name
        signals.insert(
            final_name.clone(),
            crate::state::app_state::SignalInfo {
                reader: reader.clone(),
                original_name: base_name,  // Store the ORIGINAL name from the file
            },
        );

        exposed_headers.push(final_name);
    }

    let file_name = request
        .path
        .rsplit('/')
        .next()
        .unwrap_or("unknown")
        .to_string();

    // Generate UUID for this file
    let file_id = "123".to_string();

    Json(FileReadResponse {
        id: file_id,
        name: file_name,
        path: request.path.clone(),
        source: request.path,
        headers: Some(exposed_headers),
        desc: None,
        tags: None,
        created_at: None,
        source_url: None,
    })
    .into_response()
}


async fn ws_fetch(
    State(state): State<AppState>,
    Path(signal_name): Path<String>,
    ws: WebSocketUpgrade,
) -> impl IntoResponse {
    let signal_info = {
        let signals = state.signals.read().await;
        signals.get(&signal_name).cloned()
    };

    let signal_info = match signal_info {
        Some(info) => info,
        None => {
            error!("Signal not found: {}", signal_name);
            return StatusCode::NOT_FOUND.into_response();
        }
    };

    // 🔒 reader will be locked inside the websocket handler
    ws.on_upgrade(move |socket| {
        handle_ws_fetch(socket, signal_info.reader, signal_info.original_name)
    })
}


async fn list_readers(
    State(state): State<AppState>,
) -> impl IntoResponse {
    // signals: HashMap<String, SignalInfo>
    let signals = state.signals.read().await;

    // Group by Arc pointer address
    let mut groups: HashMap<usize, Vec<String>> = HashMap::new();

    for (_key, info) in signals.iter() {
        // get raw pointer address for grouping
        let ptr = Arc::as_ptr(&info.reader) as usize;
        groups.entry(ptr).or_default().push(info.original_name.clone());
    }

    // Build response
    let mut out: Vec<ReaderSummary> = Vec::with_capacity(groups.len());
    for (ptr, mut names) in groups {
        // unique headers
        names.sort();
        names.dedup();
        let id = format!("{:x}", ptr);
        out.push(ReaderSummary {
            id,
            signals_count: names.len(),
            headers: names,
        });
    }

    Json(out)
}

// --- handler: reader_headers ---
async fn reader_headers(
    State(state): State<AppState>,
    Path(reader_id): Path<String>,
) -> impl IntoResponse {
    // parse hex id
    let ptr_res = usize::from_str_radix(&reader_id, 16);
    let ptr = match ptr_res {
        Ok(p) => p,
        Err(_) => return StatusCode::BAD_REQUEST.into_response(),
    };

    let signals = state.signals.read().await;

    // collect headers for matching pointer
    let mut headers: Vec<String> = Vec::new();
    for (_k, info) in signals.iter() {
        if Arc::as_ptr(&info.reader) as usize == ptr {
            headers.push(info.original_name.clone());
        }
    }

    if headers.is_empty() {
        return StatusCode::NOT_FOUND.into_response();
    }

    headers.sort();
    headers.dedup();

    Json(ReaderHeaders {
        id: reader_id,
        headers,
    }).into_response()
}