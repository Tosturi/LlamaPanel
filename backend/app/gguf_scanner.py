import re
from pathlib import Path

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


# Reading a GGUF header (via gguf.GGUFReader) is the expensive part of a scan -
# it's what makes /api/models and the periodic /api/server/status poll slow on
# large model directories. Cache by (path, mtime) so an unchanged file is only
# parsed once per process lifetime instead of on every request.
_metadata_cache: dict[str, tuple[float, dict]] = {}


def _read_gguf_metadata_cached(path: Path, mtime: float) -> dict:
    cached = _metadata_cache.get(str(path))
    if cached is not None and cached[0] == mtime:
        return cached[1]
    meta = _read_gguf_metadata(path)
    _metadata_cache[str(path)] = (mtime, meta)
    return meta


def _read_gguf_metadata(path: Path) -> dict:
    """Read only the GGUF header/metadata (no tensor data)."""
    try:
        import gguf  # local import: optional dep, keep scanner usable without it in tests

        reader = gguf.GGUFReader(str(path))
        fields = reader.fields

        def get_str(key: str) -> str | None:
            f = fields.get(key)
            if f is None or not f.parts:
                return None
            try:
                return bytes(f.parts[f.data[-1]]).decode("utf-8", errors="ignore")
            except Exception:
                return None

        def get_int(key: str) -> int | None:
            f = fields.get(key)
            if f is None or not f.parts:
                return None
            try:
                return int(f.parts[f.data[-1]][0])
            except Exception:
                return None

        arch = get_str("general.architecture")
        file_type_raw = get_int("general.file_type")
        ctx_len = get_int(f"{arch}.context_length") if arch else None
        name = get_str("general.name")

        return {
            "architecture": arch,
            "file_type": FILE_TYPE_NAMES.get(file_type_raw, str(file_type_raw) if file_type_raw is not None else None),
            "context_length": ctx_len,
            "name": name,
        }
    except Exception:
        # Corrupt file, unsupported version, or `gguf` not installed - degrade gracefully.
        return {}


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

    models: list[ModelInfo] = []

    for base, parts in groups.items():
        parts.sort(key=lambda t: t[0])
        entry_path = parts[0][1]
        meta = _read_gguf_metadata_cached(entry_path, entry_path.stat().st_mtime)
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
        stat = path.stat()
        meta = _read_gguf_metadata_cached(path, stat.st_mtime)
        size = stat.st_size
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
