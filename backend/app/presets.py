"""Named (model_id, flags) bundles persisted as one versioned JSON file.

Format history (see app.storage for the wrapper and migration mechanics):

- v0: a bare JSON list of {"name", "model_id", "flags"} (before versioning).
- v1: {"version": 1, "presets": [...]} - same entries, wrapped.
- v2: entries gain "updated_at" (unix time, null for migrated ones).

Flags are stored under the keys from FLAG_SCHEMA, and llama-server's CLI
changes over time. Two things keep old presets usable when it does:

- normalize_flags() runs on every read: renamed keys are mapped through
  FLAG_RENAMES and values are coerced to the type the schema now declares.
  That is data-driven, so a flag change is a schema edit plus a rename
  entry, not a new format version.
- Unknown keys are kept, never dropped. build_args() ignores them, so a
  preset saved by a newer LlamaPanel still starts fine on an older one and
  loses nothing when going back up.

Routers only see list/upsert/delete; a format change is a new migration
here, not a change in the API layer.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Iterable, Optional

from app.flags import normalize_flags
from app.storage import JsonDocumentStore

FORMAT_VERSION = 2


def _migrate_v0_to_v1(payload: Any) -> list:
    # v0 was the bare list; anything else means a file we can't interpret.
    return payload if isinstance(payload, list) else []


def _migrate_v1_to_v2(payload: Any) -> list:
    items = payload if isinstance(payload, list) else []
    return [{**p, "updated_at": p.get("updated_at")} for p in items if isinstance(p, dict)]


MIGRATIONS = {0: _migrate_v0_to_v1, 1: _migrate_v1_to_v2}


def _normalize_entry(p: dict) -> dict:
    return {
        "name": p["name"],
        "model_id": p["model_id"],
        "flags": normalize_flags(p.get("flags") or {}),
        "updated_at": p.get("updated_at"),
    }


class PresetStore:
    def __init__(self, path: Path) -> None:
        self._store = JsonDocumentStore(
            path, key="presets", version=FORMAT_VERSION, migrations=MIGRATIONS, empty=list,
        )

    @property
    def path(self) -> Path:
        return self._store.path

    def adopt_legacy_file(self, candidates: Iterable[Path]) -> Optional[Path]:
        return self._store.adopt_legacy_file(candidates)

    def list(self) -> list[dict]:
        return [_normalize_entry(p) for p in self._store.load() if isinstance(p, dict) and "name" in p]

    def upsert(self, name: str, model_id: str, flags: dict) -> dict:
        preset = _normalize_entry(
            {"name": name, "model_id": model_id, "flags": flags, "updated_at": time.time()}
        )
        self._store.update(lambda items: [p for p in items if p.get("name") != name] + [preset])
        return preset

    def delete(self, name: str) -> bool:
        removed = {"any": False}

        def drop(items: list) -> list:
            remaining = [p for p in items if p.get("name") != name]
            removed["any"] = len(remaining) != len(items)
            return remaining

        self._store.update(drop)
        return removed["any"]
