# plotune_pltx.py
# PLTX v2 - async, chunked, compressed timeseries container for Plotune
# - 1 chunk = 1 signal
# - header & metadata written at SAVE (finalize)
# - data arrives async from multiple sockets; per-signal buffers
# - index has (offset, min_ts, max_ts) for fast range queries

import asyncio
import io
import os
import time
import struct
from typing import Dict, List, Tuple, Iterable, Optional

# ---- optional compression backends ----
try:
    import zstandard as zstd
except Exception:
    zstd = None

try:
    import lz4.frame as lz4f
except Exception:
    lz4f = None

import zlib  # fallback

MAGIC = b"PLTX"  # file magic
CHUNK_MAGIC = b"CHNK"
INDEX_MAGIC = b"IDXT"
FOOTER_MAGIC = b"FTER"

# compression codes
COMP_NONE = 0
COMP_ZLIB = 1
COMP_LZ4 = 2
COMP_ZSTD = 3

RECORD_FMT = "<dd"  # (timestamp: float64, value: float64)
RECORD_SIZE = struct.calcsize(RECORD_FMT)

# chunk header layout (after CHNK magic):
# signal_id(u32) n(u32) raw_len(u32) comp_len(u32) min_ts(f64) max_ts(f64)
CHUNK_HDR_FMT = "<IIIIdd"
CHUNK_HDR_SIZE = struct.calcsize(CHUNK_HDR_FMT)

HEADER_PREFIX_FMT = (
    "<4sBBdH"  # MAGIC, version(u8), comp(u8), created(f64), sig_count(u16)
)
HEADER_PREFIX_SIZE = struct.calcsize(HEADER_PREFIX_FMT)

INDEX_ENTRY_FMT = "<IQdd"  # sid(u32), off(u64), min_ts(f64), max_ts(f64)
INDEX_ENTRY_SIZE = struct.calcsize(INDEX_ENTRY_FMT)

FOOTER_FMT = "<4sQ"  # FOOTER_MAGIC, index_offset(u64)
FOOTER_SIZE = struct.calcsize(FOOTER_FMT)


def _pick_compression(name: Optional[str]) -> int:
    name = (name or "zstd").lower()
    if name == "none":
        return COMP_NONE
    if name == "zstd" and zstd is not None:
        return COMP_ZSTD
    if name == "lz4" and lz4f is not None:
        return COMP_LZ4
    return COMP_ZLIB


def _compress(data: bytes, comp: int, level: int = 3) -> bytes:
    if comp == COMP_NONE:
        return data
    if comp == COMP_ZSTD and zstd is not None:
        cctx = zstd.ZstdCompressor(level=level)
        return cctx.compress(data)
    if comp == COMP_LZ4 and lz4f is not None:
        return lz4f.compress(data)
    return zlib.compress(data, level)


def _decompress(data: bytes, comp: int) -> bytes:
    if comp == COMP_NONE:
        return data
    if comp == COMP_ZSTD and zstd is not None:
        dctx = zstd.ZstdDecompressor()
        return dctx.decompress(data)
    if comp == COMP_LZ4 and lz4f is not None:
        return lz4f.decompress(data)
    return zlib.decompress(data)


# ----------------------- ASYNC WRITER -----------------------


class AsyncPltWriter:
    """
    Async recorder:
      - call add_signal_meta(...) for each signal when known (can be before/after Record)
      - call record_point(signal_name_or_id, ts, value) anytime (from sockets)
      - start(): spawns periodic flush task
      - stop_and_save(final_path): seals file (writes header + copy chunks + index + footer)
    Data chunks are first appended to a temp chunk file (no header). On save, we write header to final,
    then stream-copy chunks while building a final index (offsets in the final file).
    """

    def __init__(
        self,
        final_path: str,
        temp_dir: Optional[str] = None,
        compression: str = "zstd",
        chunk_records: int = 2048,
        flush_interval_sec: float = 0.5,
        fsync_every_n_chunks: int = 8,
    ):
        self.version = 2
        self.final_path = final_path
        base = os.path.basename(final_path)
        tdir = temp_dir or os.path.dirname(final_path) or "."
        os.makedirs(tdir, exist_ok=True)
        self.tmp_path = os.path.join(tdir, f".{base}.pltx.tmpchunks")
        self.meta_path = os.path.join(
            tdir, f".{base}.pltx.meta"
        )  # optional (not used for now)

        self.comp = _pick_compression(compression)
        self.created = float(time.time())
        self.chunk_records = int(chunk_records)
        self.flush_interval = float(flush_interval_sec)
        self.fsync_every = int(max(0, fsync_every_n_chunks))

        # signal registries
        self._signals_by_id: Dict[int, Dict[str, str]] = {}
        self._signals_by_name: Dict[str, int] = {}
        self._next_sid = 1

        # per-signal buffers (timestamps, values)
        self._buf_ts: Dict[int, List[float]] = {}
        self._buf_val: Dict[int, List[float]] = {}

        # file handles & locks
        self._tmp_f = open(self.tmp_path, "wb")
        self._tmp_lock = asyncio.Lock()
        self._chunks_written = 0

        # async helpers
        self._flush_task: Optional[asyncio.Task] = None
        self._running = False

    # ---- public API ----

    def add_signal_meta(
        self, name: str, unit: str = "", description: str = "", source: str = ""
    ) -> int:
        """Register/ensure a signal exists; returns signal_id."""
        if name in self._signals_by_name:
            return self._signals_by_name[name]
        sid = self._next_sid
        self._next_sid += 1
        self._signals_by_name[name] = sid
        self._signals_by_id[sid] = {
            "name": name,
            "unit": unit,
            "description": description,
            "source": source,
        }
        self._buf_ts[sid] = []
        self._buf_val[sid] = []
        return sid

    def get_signal_id(self, name_or_id) -> int:
        if isinstance(name_or_id, int):
            return name_or_id
        return self.add_signal_meta(str(name_or_id))

    async def start(self):
        """Start periodic flusher."""
        if self._running:
            return
        self._running = True
        self._flush_task = asyncio.create_task(self._periodic_flush())

    async def stop_and_save(self):
        """Flush everything and build final file atomically."""
        # stop periodic flush
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None

        # final flush of all buffers
        await self._flush_all()

        # close temp file for writing
        try:
            self._tmp_f.flush()
            os.fsync(self._tmp_f.fileno())
        except Exception:
            pass
        self._tmp_f.close()

        # assemble final file (header + chunks + index + footer) via streaming copy
        tmp_idx_entries = await asyncio.to_thread(self._scan_tmp_for_index_entries)
        await asyncio.to_thread(self._build_final_from_tmp, tmp_idx_entries)

        # cleanup temp files
        try:
            os.remove(self.tmp_path)
        except Exception:
            pass
        try:
            os.remove(self.meta_path)
        except Exception:
            pass

    async def record_point(self, signal_name_or_id, ts: float, value: float):
        """Append a single (ts,value) to signal buffer; chunk if needed."""
        sid = self.get_signal_id(signal_name_or_id)
        self._buf_ts[sid].append(float(ts))
        self._buf_val[sid].append(float(value))
        if len(self._buf_ts[sid]) >= self.chunk_records:
            await self._flush_signal(sid)

    async def record_batch(
        self, signal_name_or_id, timestamps: Iterable[float], values: Iterable[float]
    ):
        """Append many points."""
        sid = self.get_signal_id(signal_name_or_id)
        tsb = self._buf_ts[sid]
        vb = self._buf_val[sid]
        for t, v in zip(timestamps, values):
            tsb.append(float(t))
            vb.append(float(v))
        if len(tsb) >= self.chunk_records:
            await self._flush_signal(sid)

    # ---- internal: flushing ----

    async def _periodic_flush(self):
        try:
            while self._running:
                await asyncio.sleep(self.flush_interval)
                await self._flush_all()
        except asyncio.CancelledError:
            return

    async def _flush_all(self):
        # flush every non-empty buffer
        tasks = [
            self._flush_signal(sid)
            for sid in list(self._buf_ts.keys())
            if self._buf_ts[sid]
        ]
        if tasks:
            await asyncio.gather(*tasks)

    async def _flush_signal(self, sid: int):
        ts = self._buf_ts[sid]
        vs = self._buf_val[sid]
        if not ts:
            return
        # move out for thread-safe write
        out_ts, out_vs = ts[:], vs[:]
        self._buf_ts[sid].clear()
        self._buf_val[sid].clear()
        await self._append_chunk_to_tmp(sid, out_ts, out_vs)

    async def _append_chunk_to_tmp(
        self, sid: int, ts_list: List[float], val_list: List[float]
    ):
        if not ts_list:
            return
        # pack records
        rec_buf = io.BytesIO()
        n = 0
        min_ts = float("inf")
        max_ts = float("-inf")
        for t, v in zip(ts_list, val_list):
            rec_buf.write(struct.pack(RECORD_FMT, float(t), float(v)))
            if t < min_ts:
                min_ts = t
            if t > max_ts:
                max_ts = t
            n += 1
        raw = rec_buf.getvalue()
        comp = _compress(raw, self.comp)

        hdr = io.BytesIO()
        hdr.write(CHUNK_MAGIC)
        hdr.write(
            struct.pack(
                CHUNK_HDR_FMT, sid, n, len(raw), len(comp), float(min_ts), float(max_ts)
            )
        )

        # write to tmp file under lock; use to_thread to avoid blocking loop
        async with self._tmp_lock:

            def _write():
                self._tmp_f.write(hdr.getvalue())
                self._tmp_f.write(comp)
                self._chunks_written += 1
                if self.fsync_every and (self._chunks_written % self.fsync_every == 0):
                    self._tmp_f.flush()
                    os.fsync(self._tmp_f.fileno())

            await asyncio.to_thread(_write)

    # ---- temp scanning & final assembly ----

    def _scan_tmp_for_index_entries(self) -> List[Tuple[int, int, float, float, int]]:
        """
        Returns list of tuples for each chunk in temp:
          (sid, chunk_total_size, min_ts, max_ts, comp_len)
        Actually we also need to know how many bytes to copy per chunk. We compute:
          chunk_total_size = 4 + CHUNK_HDR_SIZE + comp_len
        """
        entries = []
        with open(self.tmp_path, "rb") as f:
            while True:
                pos = f.tell()
                mg = f.read(4)
                if not mg:
                    break
                if mg != CHUNK_MAGIC:
                    raise ValueError("Temp file corrupted: bad CHUNK magic")
                hdr_bytes = f.read(CHUNK_HDR_SIZE)
                if len(hdr_bytes) != CHUNK_HDR_SIZE:
                    raise ValueError("Temp file corrupted: incomplete chunk header")
                sid, n, raw_len, comp_len, mn, mx = struct.unpack(
                    CHUNK_HDR_FMT, hdr_bytes
                )
                # skip payload
                f.seek(comp_len, os.SEEK_CUR)
                total_size = 4 + CHUNK_HDR_SIZE + comp_len
                entries.append((sid, total_size, mn, mx, comp_len))
        return entries

    def _write_header_to_final(
        self, f, signals_sorted: List[Tuple[int, Dict[str, str]]]
    ):
        # Header: MAGIC, version, comp, created, sig_count, then per-signal metadata
        f.write(
            struct.pack(
                HEADER_PREFIX_FMT,
                MAGIC,
                self.version,
                self.comp,
                self.created,
                len(signals_sorted),
            )
        )
        for sid, meta in signals_sorted:

            def _wstr(s: str):
                b = s.encode("utf-8")
                f.write(struct.pack("<H", len(b)))
                f.write(b)

            f.write(struct.pack("<I", sid))
            _wstr(meta.get("name", ""))
            _wstr(meta.get("unit", ""))
            _wstr(meta.get("description", ""))
            _wstr(meta.get("source", ""))

    def _build_final_from_tmp(
        self, tmp_entries: List[Tuple[int, int, float, float, int]], attempt=0
    ):
        attempt += 1
        try:
            # open final tmp, then atomic rename
            final_tmp = self.final_path + ".part"
            os.makedirs(os.path.dirname(self.final_path) or ".", exist_ok=True)
            with open(final_tmp, "wb") as out_f:
                # header
                # sort signals by id for stable order
                sigs_sorted = sorted(self._signals_by_id.items(), key=lambda kv: kv[0])
                self._write_header_to_final(out_f, sigs_sorted)

                # copy chunks while building final index (offsets refer to out_f)
                index_entries: List[Tuple[int, int, float, float]] = []
                with open(self.tmp_path, "rb") as src:
                    for sid, total_size, mn, mx, _comp_len in tmp_entries:
                        off = out_f.tell()
                        # copy exactly total_size bytes
                        chunk = src.read(total_size)
                        if len(chunk) != total_size:
                            raise ValueError("Temp changed during copy")
                        out_f.write(chunk)
                        index_entries.append((sid, off, mn, mx))

                # write index
                index_off = out_f.tell()
                out_f.write(INDEX_MAGIC)
                out_f.write(struct.pack("<I", len(index_entries)))
                for sid, off, mn, mx in index_entries:
                    out_f.write(struct.pack(INDEX_ENTRY_FMT, sid, off, mn, mx))

                # footer
                out_f.write(struct.pack(FOOTER_FMT, FOOTER_MAGIC, index_off))
                out_f.flush()
                try:
                    os.fsync(out_f.fileno())
                except Exception:
                    pass

            # atomic promote
            os.replace(final_tmp, self.final_path)
        except:
            from time import sleep

            sleep(1)
            self._build_final_from_tmp(tmp_entries, attempt)

    # ---- util ----

    def list_registered_signals(self) -> List[Tuple[int, str]]:
        return [
            (sid, meta["name"]) for sid, meta in sorted(self._signals_by_id.items())
        ]


# -------------------------- READER --------------------------


class PltReader:
    def __init__(self, path: str):
        self.path = path
        self._f = open(path, "rb")
        self.version: int = 0
        self.comp: int = COMP_ZLIB
        self.created: float = 0.0
        self.signals: Dict[int, Dict[str, str]] = {}
        self.index: Dict[int, List[Tuple[int, float, float]]] = {}
        self._read_header()
        self._read_footer_and_index()

    def close(self):
        try:
            self._f.close()
        except Exception:
            pass

    def _read_header(self):
        f = self._f
        head = f.read(HEADER_PREFIX_SIZE)
        magic, ver, comp, created, sig_count = struct.unpack(HEADER_PREFIX_FMT, head)
        if magic != MAGIC:
            raise ValueError("Not a PLTX file")
        self.version = ver
        self.comp = comp
        self.created = created
        self.signals = {}
        for _ in range(sig_count):
            sid = struct.unpack("<I", f.read(4))[0]

            def _rstr():
                ln = struct.unpack("<H", f.read(2))[0]
                return f.read(ln).decode("utf-8")

            name = _rstr()
            unit = _rstr()
            desc = _rstr()
            src = _rstr()
            self.signals[sid] = {
                "name": name,
                "unit": unit,
                "description": desc,
                "source": src,
            }

    def _read_footer_and_index(self):
        f = self._f
        f.seek(-FOOTER_SIZE, os.SEEK_END)
        foot_magic, idx_off = struct.unpack(FOOTER_FMT, f.read(FOOTER_SIZE))
        if foot_magic != FOOTER_MAGIC:
            raise ValueError("Footer missing")
        f.seek(idx_off, os.SEEK_SET)
        if f.read(4) != INDEX_MAGIC:
            raise ValueError("Index magic missing")
        n = struct.unpack("<I", f.read(4))[0]
        self.index = {}
        for _ in range(n):
            sid, off, mn, mx = struct.unpack(INDEX_ENTRY_FMT, f.read(INDEX_ENTRY_SIZE))
            self.index.setdefault(sid, []).append((off, mn, mx))

    def list_signals(self) -> List[Tuple[int, str]]:
        return [(sid, meta["name"]) for sid, meta in self.signals.items()]

    def iter_chunks(self, signal_id: int) -> Iterable[Tuple[List[float], List[float]]]:
        """Iterate all chunks for the signal (memory friendly)."""
        if signal_id not in self.index:
            return
        f = self._f
        for off, _mn, _mx in self.index[signal_id]:
            f.seek(off, os.SEEK_SET)
            if f.read(4) != CHUNK_MAGIC:
                raise ValueError("Chunk magic mismatch")
            sid, n, raw_len, comp_len, mn, mx = struct.unpack(
                CHUNK_HDR_FMT, f.read(CHUNK_HDR_SIZE)
            )
            if sid != signal_id:
                raise ValueError("Index points to wrong signal")
            comp_payload = f.read(comp_len)
            raw = _decompress(comp_payload, self.comp)
            if len(raw) != raw_len:
                raise ValueError("Decompressed length mismatch")
            ts_list, val_list = [], []
            view = memoryview(raw)
            for i in range(n):
                rec = view[i * RECORD_SIZE : (i + 1) * RECORD_SIZE]
                ts, val = struct.unpack(RECORD_FMT, rec)
                ts_list.append(ts)
                val_list.append(val)
            yield ts_list, val_list

    def iter_time_range(
        self, signal_id: int, t1: float, t2: float
    ) -> Iterable[Tuple[List[float], List[float]]]:
        """Only read chunks intersecting [t1, t2], filter inside."""
        if signal_id not in self.index:
            return
        f = self._f
        for off, mn, mx in self.index[signal_id]:
            if mx < t1 or mn > t2:
                continue
            f.seek(off, os.SEEK_SET)
            if f.read(4) != CHUNK_MAGIC:
                raise ValueError("Chunk magic mismatch")
            sid, n, raw_len, comp_len, _mn, _mx = struct.unpack(
                CHUNK_HDR_FMT, f.read(CHUNK_HDR_SIZE)
            )
            if sid != signal_id:
                raise ValueError("Index points to wrong signal")
            comp_payload = f.read(comp_len)
            raw = _decompress(comp_payload, self.comp)
            view = memoryview(raw)
            ts_list, val_list = [], []
            for i in range(n):
                rec = view[i * RECORD_SIZE : (i + 1) * RECORD_SIZE]
                ts, val = struct.unpack(RECORD_FMT, rec)
                if t1 <= ts <= t2:
                    ts_list.append(ts)
                    val_list.append(val)
            if ts_list:
                yield ts_list, val_list

    def read_signal_all(self, signal_id: int) -> Tuple[List[float], List[float]]:
        ts_all, val_all = [], []
        for ts, vs in self.iter_chunks(signal_id):
            ts_all.extend(ts)
            val_all.extend(vs)
        return ts_all, val_all
