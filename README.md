# Plotune – Simple Reader Extension

`plotune_simple_reader_extension` is a lightweight **Rust-based extension for Plotune** that reads `.pltx` recording files and streams signal data over **WebSocket**.

It is designed for:
- High-performance offline data playback
- Low memory usage
- Native integration with Plotune’s signal pipeline

---

## ✨ Features

- 📂 Read `.pltx` recording files
- 📡 Stream signal data via WebSocket
- 🧩 Chunk-based, memory-efficient reading
- 🧵 Thread-safe file access
- ⚡ Very small release binary size
- 🐧 Linux & 🪟 Windows support

---

## 🧠 Why PLTX?

The **PLTX format** is optimized for large-scale time-series recordings:

- Indexed binary layout for fast random access
- Chunked data blocks for efficient streaming
- Per-signal metadata (name, unit, description, source)
- Optional compression support
- Designed for long recordings and high-frequency signals

This extension takes advantage of the PLTX index to:
- Read only required chunks
- Avoid loading entire files into memory
- Stream data progressively over WebSocket

---

## 🏗 Architecture Overview

```

Plotune Client
|
|  ws://host:port/fetch/{signal_name}
v
Axum WebSocket Server
|
v
PltxReader (Rust)
├── File Header
├── Signal Index
├── Chunk Reader
└── Decompression Layer

````

### Signal Exposure Model

- Signals are exposed **by name**
- No `reader_id` is required on the WebSocket API
- If multiple files contain the same signal name, suffixes are added automatically:
  - `Voltage`
  - `Voltage_1`
  - `Voltage_2`

---

## 📡 WebSocket Payload Format

Each WebSocket message is sent as JSON:

```json
{
  "timestamp": 123.456,
  "value": 78.9,
  "desc": "",
  "seq": 42,
  "end_flag": false
}
````

### Fields

| Field       | Type     | Description                               |
| ----------- | -------- | ----------------------------------------- |
| `timestamp` | `f64`    | Timestamp read directly from PLTX data    |
| `value`     | `f64`    | Signal value                              |
| `desc`      | `string` | Reserved (currently empty)                |
| `seq`       | `u64`    | Sequential packet counter                 |
| `end_flag`  | `bool`   | `true` when signal data is fully streamed |

📌 When `end_flag = true` is sent, the WebSocket connection is closed.

---

## 🔌 HTTP / WebSocket API

### ➕ Read File

```
POST /read-file
```

**Request**

```json
{
  "mode": "offline",
  "path": "data/recording.pltx"
}
```

**Response**

```json
{
  "name": "recording.pltx",
  "path": "data/recording.pltx",
  "headers": [
    "Voltage",
    "Current",
    "Temperature_1"
  ]
}
```

The `headers` field contains the **signal names** that can be requested via WebSocket.

---

### 📡 Fetch Signal (WebSocket)

```
ws://127.0.0.1:PORT/fetch/{signal_name}
```

**Example**

```
ws://127.0.0.1:59034/fetch/Voltage
```

---

## 🛠 Build

### Debug

```bash
cargo build
```

### Release

```bash
cargo build --release
```

### Linux MUSL (portable binary)

```bash
rustup target add x86_64-unknown-linux-musl
cargo build --release --target x86_64-unknown-linux-musl
```

Output:

```
target/x86_64-unknown-linux-musl/release/plotune_simple_reader_extension
```

---

## 🧵 Thread Safety Notes

* `PltxReader` is shared as:

  ```rust
  Arc<Mutex<PltxReader>>
  ```
* File I/O is protected with `Mutex<File>`
* Multiple WebSocket clients can safely stream from the same file
* Reading is performed chunk-by-chunk to minimize memory usage

---

## 🎯 Intended Use Cases

* Plotune GUI signal playback
* Offline telemetry analysis
* Long-duration recording inspection
* Academic and engineering projects


---

## 👨‍💻 Author

**Plotune Team**
Rust • Systems Programming • Data Visualization

