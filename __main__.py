import sys
import threading
import uvicorn
import os
import json
import logging
import socket
import time

from fastapi import FastAPI
from pystray import Icon as pystray_icon, MenuItem as pystray_menu_item
from PIL import Image
import requests
import asyncio

from core.routes import router

# BASE_PATH: PyInstaller tek-dosya (frozen) durumuna göre
if getattr(sys, 'frozen', False):
    BASE_PATH = os.path.dirname(sys.executable)
else:
    BASE_PATH = os.path.dirname(__file__)

__DEBUG__ = False

# --- Logging: stdout/stderr yoksa dosyaya yazalım (noconsole için) ---
LOG_PATH = os.path.join(BASE_PATH, "extension_log.txt")
# Basit logging konfigürasyonu
stream = sys.stdout if sys.stdout is not None else open(LOG_PATH, "a", encoding="utf-8")
logging.basicConfig(
    level=logging.WARNING if not __DEBUG__ else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler(stream)]
)
logger = logging.getLogger(__name__)

# Ayrıca stdout/stderr'i de dosyaya yönlendir (PyInstaller --noconsole için)
try:
    sys.stdout = open(LOG_PATH, "a", encoding="utf-8")
    sys.stderr = sys.stdout
except Exception:
    pass

# --- HEARTBEAT ---
def send_heartbeat(ext_id, heartbeat_url):
    payload = {
        "id": ext_id,
        "timestamp": time.time()
    }
    try:
        r = requests.post(heartbeat_url, json=payload, timeout=2)
        if r.status_code == 200:
            logger.info(f"Heartbeat sent: {r.status_code}")
            return True
        else:
            logger.warning(f"Heartbeat failed: {r.status_code}")
            return False
    except Exception as e:
        logger.exception("Heartbeat failed:")
        return False

async def heartbeat_loop(ext_id, heartbeat_url, interval=5, max_failures=2):
    fail_count = 0
    while True:
        success = send_heartbeat(ext_id, heartbeat_url)
        if success:
            fail_count = 0
        else:
            fail_count += 1
            logger.warning(f"Failed heartbeats: {fail_count}/{max_failures}")
            if fail_count >= max_failures:
                logger.error("Max failures reached, shutting down extension...")
                try:
                    from __main__ import icon  # veya global icon
                    if icon:
                        icon.stop()
                except Exception:
                    pass

                os._exit(1)
        await asyncio.sleep(interval)

def start_heartbeat_thread(ext_id, heartbeat_url):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(heartbeat_loop(ext_id, heartbeat_url))

# --- CONFIG LOAD ---
def load_config():
    plugin_path = os.path.join(BASE_PATH, "plugin.json")
    try:
        with open(plugin_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.exception(f"plugin.json not found at {plugin_path}")
        return {"connection": {"ip": "127.0.0.1", "port": 8100}}
    except json.JSONDecodeError:
        logger.exception(f"Invalid JSON in {plugin_path}")
        return {"connection": {"ip": "127.0.0.1", "port": 8100}}

# --- FASTAPI UYGULAMA ---
def create_app(config: dict) -> FastAPI:
    app = FastAPI(title="Sample Data Stream",
                  description="Example Live Data Stream on Web-Socket Configuration",
                  version="1.0.0")
    app.include_router(router)
    return app

# --- UVICORN SERVER (daha güvenli: Config/Server) ---
from uvicorn import Config as UvicornConfig, Server as UvicornServer

def run_server(ip: str, port: int, app: FastAPI):
    try:
        logger.info(f"Starting uvicorn on {ip}:{port}")
        config = UvicornConfig(app=app, host=ip, port=port, log_level="info", access_log=True)
        server = UvicornServer(config)
        # blocking run: çalıştırıldığı thread'de sürekli çalışacak
        server.run()
    except Exception:
        logger.exception("Uvicorn server failed:")

# --- Helper: server ayağa kalkana kadar bekle ---
def wait_for_port(host: str, port: int, timeout: float = 5.0, poll_interval: float = 0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(poll_interval)
    return False

# --- MAIN ---
def main():
    logger.info("Extension starting...")
    config = load_config()
    conn = config.get("connection", {})
    ip = conn.get("ip", "127.0.0.1")
    port = conn.get("port", 8100)

    # register (remote server)
    try:
        url = "http://127.0.0.1:8000/register"
        r = requests.post(url, json=config, timeout=3)
        logger.info(f"Register response: {r.status_code} {r.text[:200]}")
    except Exception:
        logger.exception("Register request failed")

    plugin_name = config.get("name", "Unnamed Extension")
    app = create_app(config)

    # Start server thread (daemon=False => ana process kapanana kadar açık kalır)
    server_thread = threading.Thread(target=run_server, args=(ip, port, app), daemon=False)
    server_thread.start()

    # wait until server port is listening before moving on (important)
    started = wait_for_port(ip, port, timeout=8.0)
    if not started:
        logger.error(f"Server did not start and listen on {ip}:{port} within timeout. Check logs/firewall.")
    else:
        logger.info(f"Server is up on {ip}:{port}")

    # Heartbeat thread (daemon ok)
    heartbeat_thread = threading.Thread(
        target=start_heartbeat_thread,
        args=(config.get("id"), "http://127.0.0.1:8000/heartbeat"),
        daemon=True
    )
    heartbeat_thread.start()

    # icon
    icon_path = os.path.join(BASE_PATH, "icon.png")
    if os.path.exists(icon_path):
        image = Image.open(icon_path)
    else:
        image = Image.new('RGB', (64, 64), 'white')

    menu = (pystray_menu_item('Force Stop Extension', lambda icon: icon.stop()),)
    icon = pystray_icon("FastAPI Application", image, f"{plugin_name} Extension", menu)

    try:
        icon.run()
    except Exception:
        logger.exception("pystray icon failed")

# Global init when module import ediliyor
config = load_config()
app = create_app(config)

if __name__ == "__main__":
    main()
