use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Serialize, Deserialize)]
pub struct ExtensionConfig {
    pub name: String,
    pub id: String,
    pub version: String,
    pub description: String,
    pub mode: String,
    pub author: String,
    pub cmd: Vec<String>,
    pub enabled: bool,
    pub last_updated: String,
    pub git_path: String,
    pub category: String,
    pub post_url: String,
    pub webpage: String,
    pub file_formats: Vec<String>,
    pub ask_form: bool,
    pub connection: Connection,
    pub configuration: Value,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct Connection {
    pub ip: String,
    pub port: u16,
    pub target: String,
    pub target_port: u16,
}