import json
import os
import tempfile
from threading import Lock

from app import config

_lock = Lock()

# On-disk format: {"version": 1, "presets": [...]}. The version field is
# there so a future shape change can be migrated in _load() instead of
# silently dropping the user's presets. Files written before this wrapper
# existed were a bare list; _load() still accepts those.
FORMAT_VERSION = 1


def _load() -> list[dict]:
    if not config.PRESETS_FILE.exists():
        return []
    try:
        data = json.loads(config.PRESETS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, list):  # legacy pre-versioned format
        return data
    if isinstance(data, dict) and isinstance(data.get("presets"), list):
        return data["presets"]
    return []


def _save(items: list[dict]) -> None:
    """Write atomically: serialize to a temp file in the same directory, then
    os.replace() it over the real one. A crash or power loss mid-write then
    leaves the previous file intact instead of a truncated JSON that _load()
    would read back as "no presets"."""
    payload = json.dumps({"version": FORMAT_VERSION, "presets": items}, indent=2, ensure_ascii=False)
    target = config.PRESETS_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=target.parent, prefix=target.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def list_presets() -> list[dict]:
    with _lock:
        return _load()


def upsert_preset(name: str, model_id: str, flags: dict) -> dict:
    with _lock:
        items = [p for p in _load() if p["name"] != name]
        preset = {"name": name, "model_id": model_id, "flags": flags}
        items.append(preset)
        _save(items)
        return preset


def delete_preset(name: str) -> bool:
    with _lock:
        items = _load()
        remaining = [p for p in items if p["name"] != name]
        if len(remaining) == len(items):
            return False
        _save(remaining)
        return True
