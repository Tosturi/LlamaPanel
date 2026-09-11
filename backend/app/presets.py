import json
from threading import Lock

from app import config

_lock = Lock()


def _load() -> list[dict]:
    if not config.PRESETS_FILE.exists():
        return []
    try:
        return json.loads(config.PRESETS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(items: list[dict]) -> None:
    config.PRESETS_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")


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
