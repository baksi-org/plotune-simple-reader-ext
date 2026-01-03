use axum::Router;
use tracing::{info, Level};
use tracing_subscriber;

mod routes;
mod models;
mod utils;
mod client;
mod state;

use crate::utils::conf_helper::{init_config_and_bind, get_cached_config};
use crate::state::app_state::AppState;

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_max_level(Level::INFO)
        .init();

    let state = AppState::new();

    // === CONFIG + LISTENER ===
    let listener = init_config_and_bind()
        .await
        .expect("CRITICAL INIT FAILURE");

    let config = get_cached_config();

    info!(
        "Server initialized on {}:{}",
        config.connection.ip,
        config.connection.port
    );

    client::register::register().await.unwrap();

    tokio::spawn(async {
        crate::client::register::start_heartbeat().await;
    });

    let app = Router::new()
        .merge(routes::info_routes::health_routes())
        .merge(routes::data_routes::data_routes(state.clone()));

    axum::serve(listener, app)
        .await
        .unwrap();
}
