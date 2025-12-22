from plotune_sdk import PlotuneRuntime
from plotune_sdk.models import FileMetaData, FileReadRequest
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from typing import Any, Dict, List, Optional, TypeAlias, Union
import logging
import os
import asyncio
from datetime import datetime
from core.io.reader import reader_manager, Reader
from utils import get_config, get_custom_config

logger = logging.getLogger(__name__)

class SimpleReaderAgent:
    def __init__(self):
        self.config = get_config()
        self.custom_config = get_custom_config()

        self._runtime: Optional[PlotuneRuntime] = None
        self._api: Optional[FastAPI] = None
        self._register_events()

    def _register_events(self) -> None:
        server = self.runtime.server
        server.on_event("/read-file", method="POST")(self.read_file)
        server.on_ws()(self.stream)

    async def read_file(self, request:FileReadRequest):
        assigned_signals = reader_manager.read_file(request.path)
        if assigned_signals is None:
            raise HTTPException(status_code=400, detail=f"Unsupported file format for {request.path}")

        # get header for metadata (created etc.)
        reader = reader_manager.readers[request.path]
        header = reader.get_header()
        file_ext = request.path.lower().split(".")[-1]
        tags = ["table"]
        if file_ext == "pltx":
            tags.append("pltx")
        elif file_ext == "csv":
            tags.append("csv")
        elif file_ext in ("xlsx", "xls"):
            tags.append("excel")

        meta = FileMetaData(
            name=os.path.basename(request.path),
            path=request.path,
            headers=assigned_signals,
            source=f"{file_ext.upper()} File Read - {os.path.basename(request.path)}",
            desc="Timeseries data with signals",
            tags=tags,
            created_at=datetime.fromtimestamp(header["created"]) if header.get("created") else None
        )
        print(meta)
        return meta

        
    async def stream(
        self,
        signal_name: str,
        websocket: WebSocket,
        data: Any,
    ) -> None:
        
        try:
            # find reader + original signal name via signal_map (we no longer use last_path)
            entry = reader_manager.signal_map.get(signal_name)
            if entry is None:
                raise ValueError(
                    f"Signal '{signal_name}' not registered. Call /read-file first for the file containing this signal."
                )

            reader: Reader = entry["reader"]
            orig_signal_name: str = entry["orig"]

            header = reader.get_header()
            if orig_signal_name not in header.get("signal_names", []):
                raise ValueError(f"Signal '{signal_name}' (original: '{orig_signal_name}') not found in file.")

            seq = 0
            for ts_chunk, val_chunk in reader.iter_chunks(orig_signal_name):
                for ts, val in zip(ts_chunk, val_chunk):
                    response = {
                        "timestamp": ts,
                        "value": val,
                        "desc": "",
                        "seq": seq,
                        "end_flag": False
                    }
                    await websocket.send_json(response)
                    seq += 1
            await asyncio.sleep(0.01667)
            await websocket.send_json({
                "timestamp": None,
                "value": None,
                "desc": "",
                "seq": seq,
                "end_flag": True
            })
        except Exception as e:
            await websocket.send_json({"error": str(e)})
        finally:
            await websocket.close()

    @property
    def runtime(self) -> PlotuneRuntime:
        if self._runtime:
            return self._runtime

        connection = self.config.get("connection", {})
        target = connection.get("target", "127.0.0.1")
        port = connection.get("target_port", "8000")
        core_url = f"http://{target}:{port}"

        self._runtime = PlotuneRuntime(
            ext_name=self.config.get("id"),
            core_url=core_url,
            config=self.config,
        )

        return self._runtime
    
    def start(self) -> None:
        logger.info("Starting Simple Reader Agent")
        self.runtime.start()
