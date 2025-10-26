from . import PltReader
import pandas as pd
import json
from functools import lru_cache
from typing import Dict, List, Tuple, Iterable, Optional
import os
import warnings

class Reader:
    """
    Unified reader for PLTX, CSV, Excel, HDF5, and Parquet timeseries files.
    CSV/Excel format: Columns [Time, Signal1, Signal2, ...], each row is a timestamp with signal values.
    HDF5/Parquet: Must contain 'Time' column and signal columns in a single table.
    """
    def __init__(self, path: str):
        self.path: str = path
        self.engine: str = self.get_engine()
        self.dataset = None  # For HDF5 dataset reference
        
        if self.engine == "pltx":
            self.reader = PltReader(self.path)
        elif self.engine in ("csv", "excel"):
            pass  # No special initialization needed
        elif self.engine == "hdf5":
            try:
                import h5py
                self.file = h5py.File(self.path, 'r')
                self._locate_hdf5_dataset()
            except ImportError:
                raise ImportError("h5py is required for HDF5 files")
        elif self.engine == "parquet":
            try:
                import pyarrow.parquet as pq
                self.parquet_file = pq.ParquetFile(self.path)
            except ImportError:
                raise ImportError("pyarrow is required for Parquet files")
        else:
            raise ValueError(f"Unsupported file extension for {path}")

    def get_engine(self) -> str:
        ext = os.path.splitext(self.path.lower())[-1][1:]
        extension_map = {
            'pltx': 'pltx',
            'csv': 'csv',
            'xlsx': 'excel',
            'xls': 'excel',
            'h5': 'hdf5',
            'parquet': 'parquet'
        }
        return extension_map.get(ext, 'unknown')

    def _locate_hdf5_dataset(self):
        """Find the first valid structured dataset in HDF5 file"""
        import h5py
        def find_dataset(group):
            for key in group:
                item = group[key]
                if isinstance(item, h5py.Dataset) and item.dtype.names:
                    return item
                elif isinstance(item, h5py.Group):
                    found = find_dataset(item)
                    if found:
                        return found
            return None
        
        self.dataset = find_dataset(self.file)
        if not self.dataset:
            raise ValueError("No structured dataset found in HDF5 file")

    @lru_cache(maxsize=128)
    def get_header(self) -> dict:
        if self.engine == "pltx":
            return {
                "version": self.reader.version,
                "compression": self.reader.comp,
                "created": self.reader.created,
                "signals": self.reader.signals,
                "signal_names": [meta["name"] for sid, meta in self.reader.signals.items()]
            }
        elif self.engine == "csv":
            df = pd.read_csv(self.path, nrows=0)
            return self._pandas_header(df)
        elif self.engine == "excel":
            df = pd.read_excel(self.path, nrows=0)
            return self._pandas_header(df)
        elif self.engine == "hdf5":
            if not self.dataset:
                self._locate_hdf5_dataset()
            names = list(self.dataset.dtype.names)
            signal_names = [n for n in names if n.lower() != "time"]
            return self._standard_header(signal_names)
        elif self.engine == "parquet":
            names = self.parquet_file.schema.names
            signal_names = [n for n in names if n.lower() != "time"]
            return self._standard_header(signal_names)

    def _pandas_header(self, df: pd.DataFrame) -> dict:
        """Extract header from pandas DataFrame"""
        signal_names = [col for col in df.columns if col.lower() != "time"]
        return self._standard_header(signal_names)

    def _standard_header(self, signal_names: list) -> dict:
        """Create standard header dictionary"""
        return {
            "version": None,
            "compression": None,
            "created": None,
            "signals": {str(i+1): {"name": name} for i, name in enumerate(signal_names)},
            "signal_names": signal_names
        }

    def iter_chunks(self, signal_name: str, chunk_size: int = 1000) -> Iterable[Tuple[List[float], List[float]]]:
        if signal_name.lower() == "time":
            raise ValueError("Signal name cannot be 'Time'")

        if self.engine == "pltx":
            sig_map = {name: sid for sid, name in self.reader.list_signals()}
            sid = sig_map.get(signal_name)
            if not sid:
                raise ValueError(f"Signal '{signal_name}' not found")
            yield from self.reader.iter_chunks(sid)
            
        elif self.engine in ("csv", "excel"):
            reader = pd.read_csv if self.engine == "csv" else pd.read_excel
            for chunk in reader(
                self.path, 
                usecols=['Time', signal_name], 
                chunksize=chunk_size,
                dtype={'Time': float, signal_name: float}
            ):
                if not chunk.empty:
                    yield chunk['Time'].tolist(), chunk[signal_name].tolist()
                    
        elif self.engine == "hdf5":
            if signal_name not in self.dataset.dtype.names:
                raise ValueError(f"Signal '{signal_name}' not found")
                
            n = len(self.dataset)
            for i in range(0, n, chunk_size):
                end = min(i + chunk_size, n)
                chunk = self.dataset[i:end]
                yield chunk['Time'].tolist(), chunk[signal_name].tolist()
                
        elif self.engine == "parquet":
            for batch in self.parquet_file.iter_batches(
                batch_size=chunk_size, 
                columns=['Time', signal_name]
            ):
                ts = batch.column('Time').to_numpy().tolist()
                vals = batch.column(signal_name).to_numpy().tolist()
                yield ts, vals

    @lru_cache(maxsize=128)
    def read_signal_all(self, signal_name: str) -> Tuple[List[float], List[float]]:
        if signal_name.lower() == "time":
            raise ValueError("Signal name cannot be 'Time'")

        if self.engine == "pltx":
            sig_map = {name: sid for sid, name in self.reader.list_signals()}
            sid = sig_map.get(signal_name)
            if not sid:
                raise ValueError(f"Signal '{signal_name}' not found")
            return self.reader.read_signal_all(sid)
            
        elif self.engine == "csv":
            df = pd.read_csv(self.path, usecols=['Time', signal_name])
            return df['Time'].tolist(), df[signal_name].tolist()
            
        elif self.engine == "excel":
            df = pd.read_excel(self.path, usecols=['Time', signal_name])
            return df['Time'].tolist(), df[signal_name].tolist()
            
        elif self.engine == "hdf5":
            if signal_name not in self.dataset.dtype.names:
                raise ValueError(f"Signal '{signal_name}' not found")
            return (
                self.dataset['Time'][:].tolist(),
                self.dataset[signal_name][:].tolist()
            )
            
        elif self.engine == "parquet":
            table = self.parquet_file.read(columns=['Time', signal_name])
            return (
                table.column('Time').to_numpy().tolist(),
                table.column(signal_name).to_numpy().tolist()
            )

    def close(self):
        if self.engine == "pltx":
            self.reader.close()
        elif self.engine == "hdf5" and hasattr(self, 'file'):
            self.file.close()
        # For parquet, no explicit close needed

# ReaderManager remains unchanged from the original implementation


class ReaderManager:
    AVAILABLE_FORMATS = ["pltx", "csv", "xlsx", "xls", "h5", "parquet"]
    
    def __init__(self):
        self.readers: Dict[str, Reader] = {}
        # key: assigned_signal_name -> { "orig": original_signal_name, "reader": Reader, "path": path }
        self.signal_map: Dict[str, Dict] = {}
        # optional reverse map original -> assigned (useful)
        self.signal_map_invert: Dict[str, str] = {}
        # which assigned signals belong to which path
        self.readers_signals: Dict[str, List[str]] = {}

    def get_signal_name(self, signal:str):
        origin_keys:list = list(self.signal_map.keys())
        if signal in origin_keys:
            count = origin_keys.count(signal) + 1
            return f"{signal}[{count}]"
        return signal

    def read_file(self, path:str):
        if path.lower().split(".")[-1] not in self.AVAILABLE_FORMATS:
            return None
        if path not in self.readers:
            self.readers[path] = Reader(path)
        
        signal_names = self.readers[path].get_header().get("signal_names", [])
        assigned_list = []
        for signal in signal_names:
            _signal = self.get_signal_name(signal)
            # store richer mapping so we can locate reader & original name by assigned name
            self.signal_map[_signal] = {"orig": signal, "reader": self.readers[path], "path": path}
            self.signal_map_invert[signal] = _signal
            assigned_list.append(_signal)

        # remember which assigned signals correspond to this path
        self.readers_signals[path] = assigned_list

        # return assigned signals (useful for the caller / endpoint)
        return assigned_list


reader_manager = ReaderManager()