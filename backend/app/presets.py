import json
import os
import tempfile
from pathlib import Path
from threading import Lock

# On-disk format: {"version": 1, "presets": [...]}. The version field is
# there so a future shape change can be migrated in _load() instead of
# silently dropping the user's presets. Files written before this wrapper
# existed were a bare list; _load() still accepts those.
FORMAT_VERSION = 1


class PresetStore:
    """Named (model_id, flags) bundles persisted as one JSON file.

    Routers only see list/upsert/delete; the file format and atomic-write
    dance are private so they can change (or move to a database once there
    is a second entity worth storing) without touching the API layer.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = Lock()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if isinstance(data, list):  # legacy pre-versioned format
            return data
        if isinstance(data, dict) and isinstance(data.get("presets"), list):
            return data["presets"]
        return []

    def _save(self, items: list[dict]) -> None:
        """Write atomically: serialize to a temp file in the same directory,
        then os.replace() it over the real one. A crash or power loss
        mid-write then leaves the previous file intact instead of a truncated
        JSON that _load() would read back as "no presets"."""
        payload = json.dumps({"version": FORMAT_VERSION, "presets": items}, indent=2, ensure_ascii=False)
        target = self._path
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

    def list(self) -> list[dict]:
        with self._lock:
            return self._load()

    def upsert(self, name: str, model_id: str, flags: dict) -> dict:
        with self._lock:
            items = [p for p in self._load() if p["name"] != name]
            preset = {"name": name, "model_id": model_id, "flags": flags}
            items.append(preset)
            self._save(items)
            return preset

    def delete(self, name: str) -> bool:
        with self._lock:
            items = self._load()
            remaining = [p for p in items if p["name"] != name]
            if len(remaining) == len(items):
                return False
            self._save(remaining)
            return True
