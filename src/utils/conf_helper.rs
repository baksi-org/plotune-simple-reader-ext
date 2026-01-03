use tokio::fs;
use std::sync::OnceLock;
use tracing::info;
use crate::models::extension_model::ExtensionConfig;
use tokio::net::TcpListener;

static CONFIG_CACHE: OnceLock<ExtensionConfig> = OnceLock::new();
static CORE_URL: OnceLock<String> = OnceLock::new();

pub async fn init_config_and_bind() -> Result<TcpListener, String> {
    let file_path = "plugin.json";

    let data = fs::read_to_string(file_path)
        .await
        .map_err(|e| format!("File read Error: {e} {file_path}"))?;

    let mut config: ExtensionConfig = serde_json::from_str(&data)
        .map_err(|e| format!("JSON Parse Error: {e}"))?;

    // === SERVER SOCKET BURADA AÇILIYOR ===
    let bind_addr = format!(
        "{}:{}",
        config.connection.ip,
        config.connection.port
    );

    let listener = TcpListener::bind(&bind_addr)
        .await
        .map_err(|e| format!("Bind failed: {e}"))?;

    let actual_port = listener
        .local_addr()
        .map_err(|e| format!("Addr error: {e}"))?
        .port();

    // === PORT PATCH ===
    config.connection.port = actual_port;

    // CORE URL
    let url = format!(
        "{}:{}",
        config.connection.target,
        config.connection.target_port
    );

    CORE_URL
        .set(url)
        .map_err(|_| "Core URL already initialized".to_string())?;

    CONFIG_CACHE
        .set(config)
        .map_err(|_| "Config already initialized".to_string())?;

    info!("Config initialized with dynamic port: {}", actual_port);

    Ok(listener)
}

pub fn get_cached_config() -> &'static ExtensionConfig {
    CONFIG_CACHE.get().expect("Config not initialized")
}

pub fn get_core_url() -> &'static String {
    CORE_URL.get().expect("Core URL not initialized")
}
