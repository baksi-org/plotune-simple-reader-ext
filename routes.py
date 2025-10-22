from fastapi import APIRouter, HTTPException, WebSocket
from pydantic import BaseModel, Field
from typing import Optional, Dict, Literal, List
from datetime import datetime
import uuid
import os
from simple_reader.core import reader_manager, Reader
import asyncio

router = APIRouter()

class FileMetaData(BaseModel):
    """
    A detailed metadata model for a file.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, description="A unique identifier for the file metadata.")
    name: str = Field(..., description="The name of the file.")
    path: str = Field(..., description="The file path on the system.")
    source: str = Field(..., description="The source of the file.")
    headers: Optional[List[str]] = Field(None, description="A list of headers found in the file.")
    desc: Optional[str] = Field(None, description="A description of the file's content.")
    tags: Optional[List[str]] = Field(None, description="A list of tags for the file.")
    created_at: Optional[datetime] = Field(None, description="The creation timestamp of the file.")
    source_url: Optional[str] = Field(None, description="The URL from which the file was sourced.")

class FileReadRequest(BaseModel):
    """
    A model to request reading a single file.
    """
    mode: Literal["online", "offline"] = Field(..., description="The reading mode, 'online' for a stream or 'offline' for a static read.")
    path: str = Field(..., description="The file path to be read.")


@router.post("/read-file", tags=["Tasks"], response_model=FileMetaData,
    summary="File Read Request",
    description="Reads the file at the specified path and returns its metadata.")
async def task_read_file(request: FileReadRequest):
    try:
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
            # **important**: expose assigned (unique) signal names, not original column names
            headers=assigned_signals,
            source=f"{file_ext.upper()} File Read - {os.path.basename(request.path)}",
            desc="Timeseries data with signals",
            tags=tags,
            created_at=datetime.fromtimestamp(header["created"]) if header.get("created") else None
        )
        return meta
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.websocket("/fetch/{signal_name}")
async def websocket_endpoint(websocket: WebSocket, signal_name: str):
    await websocket.accept()
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