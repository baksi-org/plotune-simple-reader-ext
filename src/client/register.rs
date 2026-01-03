use serde::Serialize;
use tracing::{info, error};
use reqwest::Client;
use std::time::{SystemTime, UNIX_EPOCH};
use crate::utils::conf_helper;

#[derive(Serialize)]
pub struct HealthPayload {
    pub id: String,
    pub timestamp: f64,
}

use tokio::time::{sleep, Duration};

pub async fn start_heartbeat() {
    let config = conf_helper::get_cached_config();
    let core_url = conf_helper::get_core_url();

    let heartbeat_url = format!("http://{}/heartbeat", core_url);
    let client = Client::new();

    info!("Heartbeat worker started for ID: {}", config.id);

    loop {
        let payload = HealthPayload {
            id: config.id.clone(),
            timestamp: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_secs_f64(),
        };

        let result = client
            .post(&heartbeat_url)
            .json(&payload)
            .send()
            .await;

        match result {
            Ok(resp) if resp.status().is_success() => {
                info!("Heartbeat sent successfully");
            }
            Ok(resp) => error!("Heartbeat server error: {}", resp.status()),
            Err(e) => error!("Heartbeat network error: {}", e),
        }

        sleep(Duration::from_secs(15)).await;
    }
}


pub async fn register() -> Result<(), String> {
    let config = conf_helper::get_cached_config();
    let core_url = conf_helper::get_core_url();

    let register_url = format!("http://{}/register", core_url);
    let client = Client::new();

    info!("Registering to Plotune Core: {}", register_url);

    client
        .post(&register_url)
        .json(config)
        .send()
        .await
        .map_err(|e| {
            error!("Registration failed: {}", e);
            format!("HTTP Error: {}", e)
        })?
        .error_for_status()
        .map_err(|e| format!("Server returned error: {}", e))?;

    info!("Successfully registered to Plotune Core!");
    Ok(())
}
