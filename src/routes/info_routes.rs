use axum::{
    routing::get,
    Router,
    http::StatusCode,
    response::{IntoResponse, Response, Html},
    Json,
};

use tokio::fs;
use tracing::{debug, error};
use serde::Serialize;


pub fn health_routes() -> Router {
    Router::new()
        .route("/", get(index_page))
        .route("/health", get(health_check))
        .route("/info", get(info_check))
        .route("/stop", get(stop_process))
}

async fn index_page() -> Response {
    fs::read_to_string("data/index.html")
        .await
        .map(Html)
        .map(IntoResponse::into_response)
        .unwrap_or_else(|e| {
            error!("Index.html read error: {}", e);
            StatusCode::NOT_FOUND.into_response()
        })
}

pub async fn info_check() -> Response {
    let config = crate::utils::conf_helper::get_cached_config();

    debug!("{} requested", config.name);
    Json(config).into_response()
}


use std::sync::atomic::{AtomicUsize, Ordering};

static HEALTH_FAIL_COUNT: AtomicUsize = AtomicUsize::new(0);
const HEALTH_FAIL_LIMIT: usize = 3;

async fn health_check() -> Response {
    let is_healthy = true; // ileride gerçek check buraya

    if is_healthy {
        HEALTH_FAIL_COUNT.store(0, Ordering::Relaxed);

        Json(HealthStatus {
            status: "ok".to_owned(),
        })
        .into_response()
    } else {
        let fails = HEALTH_FAIL_COUNT.fetch_add(1, Ordering::Relaxed) + 1;

        error!("Health check failed ({}/{})", fails, HEALTH_FAIL_LIMIT);

        if fails >= HEALTH_FAIL_LIMIT {
            error!("Health check limit exceeded, shutting down process");
            std::process::exit(1);
        }

        StatusCode::SERVICE_UNAVAILABLE.into_response()
    }
}


async fn stop_process() -> impl IntoResponse {
    error!("Stop endpoint called, shutting down process");

    // log flush için kısa gecikme opsiyonel
    tokio::spawn(async {
        tokio::time::sleep(std::time::Duration::from_millis(100)).await;
        std::process::exit(0);
    });

    StatusCode::OK
}


#[derive(Serialize)]
pub struct HealthStatus {
    status: String,
}