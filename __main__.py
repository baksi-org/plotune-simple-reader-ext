import threading
import uvicorn, os, json
from fastapi import FastAPI
from pystray import Icon as pystray_icon, MenuItem as pystray_menu_item
from PIL import Image

# Import the router, assuming simple_reader is a local package
try:
    from simple_reader.routes import router
except ImportError:
    print("Warning: The 'simple_reader' package or 'routes' module was not found.")
    print("Please ensure your project structure is correct.")
    # Fallback to a simple router if the original is not found
    from fastapi import APIRouter
    router = APIRouter()

BASE_PATH = os.path.dirname(__file__)
__DEBUG__ = False

### HEARTBEAT
import asyncio
import requests
import time
import sys

def send_heartbeat(ext_id, heartbeat_url):
    payload = {
        "id": ext_id,
        "timestamp": time.time()
    }
    try:
        r = requests.post(heartbeat_url, json=payload, timeout=2)
        if r.status_code == 200:
            print("Heartbeat sent:", r.status_code)
            return True
        else:
            print("Heartbeat failed:", r.status_code)
            return False
    except Exception as e:
        print("Heartbeat failed:", e)
        return False

async def heartbeat_loop(ext_id, heartbeat_url, interval=15, max_failures=5):
    fail_count = 0
    while True:
        success = send_heartbeat(ext_id, heartbeat_url)
        if success:
            fail_count = 0
        else:
            fail_count += 1
            print(f"Failed heartbeats: {fail_count}/{max_failures}")
            if fail_count >= max_failures:
                print("Max failures reached, shutting down extension...")
                sys.exit(1)
        await asyncio.sleep(interval)

def start_heartbeat_thread(ext_id, heartbeat_url):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(heartbeat_loop(ext_id, heartbeat_url))



def load_config():
    """Loads the application configuration from plugin.json."""
    plugin_path = os.path.join(BASE_PATH, "plugin.json")
    try:
        with open(plugin_path) as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: plugin.json not found at {plugin_path}")
        return {"connection": {"ip": "127.0.0.1", "port": 8100}}
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON in {plugin_path}")
        return {"connection": {"ip": "127.0.0.1", "port": 8100}}

def create_app(config: dict) -> FastAPI:
    """Creates and configures the FastAPI application."""
    app = FastAPI(title="Sample Data Stream",
                  description="Example Live Data Stream on Web-Socket Configuration",
                  version="1.0.0")
    app.include_router(router)
    return app

def run_server(ip: str, port: int):
    """Starts the FastAPI server using Uvicorn."""
    uvicorn.run(
        "simple_reader.__main__:app",
        host=ip,
        port=port,
        log_level="info",
        access_log=False,
        reload=__DEBUG__,
    )

def main():
    """Main function to start both the server and the system tray icon."""
    config = load_config()
    conn = config["connection"]
    ip = conn.get("ip", "127.0.0.1")
    port = conn.get("port", 8100)
    url = "http://127.0.0.1:8000/register"
    response = requests.post(url, json=config)
    
    # Get the name from the config, defaulting to 'Unnamed Extension'
    plugin_name = config.get("name", "Unnamed Extension")

    # Start the FastAPI server in a separate thread.
    # This allows the main thread to handle the system tray icon.
    server_thread = threading.Thread(target=run_server, args=(ip, port), daemon=True)
    server_thread.start()
    heartbeat_thread = threading.Thread(
        target=start_heartbeat_thread, 
        args=(config.get("id"), "http://127.0.0.1:8000/heartbeat"),
        daemon=True
    )
    heartbeat_thread.start()

    # Check if a custom icon file exists, otherwise use a default image.
    icon_path = os.path.join(BASE_PATH, "icon.png") # Assuming a file named icon.png
    if os.path.exists(icon_path):
        image = Image.open(icon_path)
    else:
        # Create a simple default icon if none is found.
        image = Image.new('RGB', (64, 64), 'white')
    
    # Define the menu for the system tray icon.
    menu = (
        pystray_menu_item('Force Stop Extension', lambda icon: icon.stop()),
    )
    
    # Create and run the system tray icon, using the plugin name in the title.
    icon = pystray_icon("FastAPI Application", image, f"{plugin_name} Extension", menu)
    icon.run()

# Main entry point for the application.
config = load_config()
app = create_app(config)

if __name__ == "__main__":
    main()
