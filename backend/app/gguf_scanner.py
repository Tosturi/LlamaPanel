import re
import struct
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import BinaryIO

from app.schemas import ModelInfo, ModelPart

# llama.cpp split naming convention: "<name>-00001-of-00005.gguf"
SPLIT_RE = re.compile(r"^(?P<base>.+)-(?P<part>\d{5})-of-(?P<total>\d{5})\.gguf$", re.IGNORECASE)

# Known general.file_type values (ggml_ftype enum) worth naming; anything else
# falls back to showing the raw integer instead of guessing.
FILE_TYPE_NAMES = {
    0: "F32", 1: "F16",
    2: "Q4_0", 3: "Q4_1", 7: "Q8_0", 8: "Q5_0", 9: "Q5_1",
    10: "Q2_K", 11: "Q3_K_S", 12: "Q3_K_M", 13: "Q3_K_L",
    14: "Q4_K_S", 15: "Q4_K_M", 16: "Q5_K_S", 17: "Q5_K_M", 18: "Q6_K",
    19: "IQ2_XXS", 20: "IQ2_XS", 21: "Q2_K_S", 22: "IQ3_XS",
    23: "IQ3_XXS", 24: "IQ1_S", 25: "IQ4_NL", 26: "IQ3_S",
    27: "IQ3_M", 28: "IQ2_S", 29: "IQ2_M", 30: "IQ4_XS", 31: "IQ1_M",
}


# Reading a GGUF header is the expensive part of a scan - it's what makes
# /api/models and the periodic /api/server/status poll slow on large model
# directories. Cache by (path, mtime) so an unchanged file is only parsed
# once per process lifetime instead of on every request.
_metadata_cache: dict[str, tuple[float, dict]] = {}


def _read_gguf_metadata_cached(path: Path, mtime: float) -> dict:
    cached = _metadata_cache.get(str(path))
    if cached is not None and cached[0] == mtime:
        return cached[1]
    meta = _read_gguf_metadata(path)
    _metadata_cache[str(path)] = (mtime, meta)
    return meta


# --- GGUF header parsing -------------------------------------------------
#
# The panel needs four values out of a model file: architecture, name,
# quantisation type and context length. The official `gguf` reader was
# built for converters, so it materialises *every* key/value pair - including
# the tokenizer's vocabulary, merges and scores, hundreds of thousands of
# entries each - as numpy views, and then walks the whole tensor-info table.
# On a 9B model that is seconds per file, all of it thrown away. This parser
# walks the KV section sequentially, skips values it does not care about
# without decoding them, and stops as soon as the four keys are in hand -
# which in practice is after the first dozen entries, long before the
# tokenizer block. Format reference: ggml/docs/gguf.md.

GGUF_MAGIC = b"GGUF"
GGUF_SUPPORTED_VERSIONS = (2, 3)

# gguf_metadata_value_type -> (struct format, byte size)
_T_UINT8, _T_INT8, _T_UINT16, _T_INT16, _T_UINT32, _T_INT32 = 0, 1, 2, 3, 4, 5
_T_FLOAT32, _T_BOOL, _T_STRING, _T_ARRAY, _T_UINT64, _T_INT64, _T_FLOAT64 = 6, 7, 8, 9, 10, 11, 12
_SCALAR_TYPES: dict[int, tuple[str, int]] = {
    _T_UINT8: ("B", 1), _T_INT8: ("b", 1), _T_UINT16: ("H", 2), _T_INT16: ("h", 2),
    _T_UINT32: ("I", 4), _T_INT32: ("i", 4), _T_FLOAT32: ("f", 4), _T_BOOL: ("?", 1),
    _T_UINT64: ("Q", 8), _T_INT64: ("q", 8), _T_FLOAT64: ("d", 8),
}

_GENERAL_KEYS = ("general.architecture", "general.name", "general.file_type")
_WANTED_COUNT = len(_GENERAL_KEYS) + 1  # + "<arch>.context_length"


class _HeaderReader:
    """Sequential little-endian reader over a file with a refillable buffer,
    so the thousands of tiny reads a KV walk needs don't each hit the OS."""

    def __init__(self, f: BinaryIO, chunk_size: int = 1 << 20) -> None:
        self._f = f
        self._chunk_size = chunk_size
        self._buf = b""
        self._pos = 0

    def take(self, n: int) -> bytes:
        if self._pos + n > len(self._buf):
            self._buf = self._buf[self._pos:] + self._f.read(max(self._chunk_size, n))
            self._pos = 0
            if len(self._buf) < n:
                raise EOFError("truncated GGUF header")
        chunk = self._buf[self._pos:self._pos + n]
        self._pos += n
        return chunk

    def skip(self, n: int) -> None:
        buffered = len(self._buf) - self._pos
        if n <= buffered:
            self._pos += n
        else:
            # Past the end of the buffer: seek instead of reading and discarding.
            self._f.seek(n - buffered, 1)
            self._buf = b""
            self._pos = 0

    def u32(self) -> int:
        return struct.unpack("<I", self.take(4))[0]

    def u64(self) -> int:
        return struct.unpack("<Q", self.take(8))[0]

    def string(self) -> str:
        return self.take(self.u64()).decode("utf-8", errors="ignore")

    def skip_string(self) -> None:
        self.skip(self.u64())


def _read_wanted_kv(f: BinaryIO) -> dict:
    """Walk the KV section and return the raw values of the keys the panel
    uses. Anything else is skipped byte-wise without being decoded."""
    r = _HeaderReader(f)
    if r.take(4) != GGUF_MAGIC:
        raise ValueError("not a GGUF file")
    version = r.u32()
    if version not in GGUF_SUPPORTED_VERSIONS:
        raise ValueError(f"unsupported GGUF version {version}")
    r.u64()  # tensor count - the tensor-info table is never read
    kv_count = r.u64()

    found: dict = {}
    ctx_key: str | None = None
    for _ in range(kv_count):
        key = r.string()
        value_type = r.u32()
        wanted = key in _GENERAL_KEYS or key == ctx_key

        if value_type == _T_STRING:
            if wanted:
                found[key] = r.string()
            else:
                r.skip_string()
        elif value_type == _T_ARRAY:
            # Arrays (vocab, merges, scores, ...) are never wanted; skip them
            # as cheaply as the element type allows.
            elem_type = r.u32()
            count = r.u64()
            if elem_type == _T_STRING:
                for _ in range(count):
                    r.skip_string()
            elif elem_type in _SCALAR_TYPES:
                r.skip(_SCALAR_TYPES[elem_type][1] * count)
            else:
                raise ValueError(f"unknown GGUF array element type {elem_type}")
        elif value_type in _SCALAR_TYPES:
            fmt, size = _SCALAR_TYPES[value_type]
            raw = r.take(size)
            if wanted:
                found[key] = struct.unpack("<" + fmt, raw)[0]
        else:
            raise ValueError(f"unknown GGUF value type {value_type}")

        if key == "general.architecture" and isinstance(found.get(key), str):
            ctx_key = f"{found[key]}.context_length"
        if len(found) == _WANTED_COUNT:
            break  # everything we need is in hand; don't walk the tokenizer
    return found


def _read_gguf_metadata(path: Path) -> dict:
    """Read only the GGUF header/metadata the panel displays (no tensor data)."""
    try:
        with open(path, "rb") as f:
            raw = _read_wanted_kv(f)
    except Exception:
        # Corrupt/truncated file, unsupported version, unreadable - degrade gracefully.
        return {}

    arch = raw.get("general.architecture")
    if not isinstance(arch, str):
        arch = None
    name = raw.get("general.name")
    if not isinstance(name, str):
        name = None
    file_type_raw = raw.get("general.file_type")
    if isinstance(file_type_raw, bool) or not isinstance(file_type_raw, int):
        file_type_raw = None
    ctx_len = raw.get(f"{arch}.context_length") if arch else None
    if isinstance(ctx_len, bool) or not isinstance(ctx_len, int):
        ctx_len = None

    return {
        "architecture": arch,
        "file_type": FILE_TYPE_NAMES.get(file_type_raw, str(file_type_raw) if file_type_raw is not None else None),
        "context_length": ctx_len,
        "name": name,
    }


def scan(directory: Path) -> list[ModelInfo]:
    if not directory.exists():
        return []

    groups: dict[str, list[tuple[int, Path]]] = {}
    singles: list[Path] = []

    for path in sorted(directory.glob("*.gguf")):
        m = SPLIT_RE.match(path.name)
        if m:
            base = m.group("base")
            part_no = int(m.group("part"))
            groups.setdefault(base, []).append((part_no, path))
        else:
            singles.append(path)

    for parts in groups.values():
        parts.sort(key=lambda t: t[0])

    # Header reads are I/O-bound (each one is an open + a few reads, and on a
    # cold cache the first read of a huge file can stall on the disk). Fan
    # them out across threads so they overlap instead of queueing up.
    entry_paths = [parts[0][1] for parts in groups.values()] + singles
    with ThreadPoolExecutor(max_workers=min(8, len(entry_paths)) or 1) as pool:
        metas = list(pool.map(lambda p: _read_gguf_metadata_cached(p, p.stat().st_mtime), entry_paths))
    meta_by_path = dict(zip(entry_paths, metas))

    models: list[ModelInfo] = []

    for base, parts in groups.items():
        entry_path = parts[0][1]
        meta = meta_by_path[entry_path]
        model_parts = [
            ModelPart(filename=p.name, path=str(p), size_bytes=p.stat().st_size)
            for _, p in parts
        ]
        models.append(ModelInfo(
            id=base,
            display_name=meta.get("name") or base,
            entry_path=str(entry_path),
            parts=model_parts,
            total_size_bytes=sum(p.size_bytes for p in model_parts),
            architecture=meta.get("architecture"),
            file_type=meta.get("file_type"),
            context_length=meta.get("context_length"),
            is_split=True,
        ))

    for path in singles:
        meta = meta_by_path[path]
        size = path.stat().st_size
        models.append(ModelInfo(
            id=path.stem,
            display_name=meta.get("name") or path.stem,
            entry_path=str(path),
            parts=[ModelPart(filename=path.name, path=str(path), size_bytes=size)],
            total_size_bytes=size,
            architecture=meta.get("architecture"),
            file_type=meta.get("file_type"),
            context_length=meta.get("context_length"),
            is_split=False,
        ))

    return sorted(models, key=lambda m: m.display_name.lower())
