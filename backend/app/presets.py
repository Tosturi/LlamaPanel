"""Named (model_id, flags) bundles persisted as one versioned JSON file.

Format history (see app.storage for the wrapper and migration mechanics):

- v0: a bare JSON list of {"name", "model_id", "flags"} (before versioning).
- v1: {"version": 1, "presets": [...]} - same entries, wrapped.
- v2: entries gain "updated_at" (unix time, null for migrated ones).

Flags are stored under FlagDef keys, and llama-server's CLI changes over
time. Two things keep old presets usable when it does:

- The injected `resolve` (flags.FlagCatalog.resolve) runs on every read:
  keys are matched against every spelling the installed binary knows,
  renamed ones re-keyed, and values coerced to the type the schema now
  declares. That is data-driven, so a llama.cpp upgrade is not a new
  format version.
- Unknown keys are kept, never dropped, and reported in `unsupported`.
  build_args() ignores them, so a preset saved against another build
  still starts fine and loses nothing when going back.

Routers only see list/upsert/delete; a format change is a new migration
here, not a change in the API layer.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from app.storage import JsonDocumentStore

FORMAT_VERSION = 2

# (stored flags) -> (flags brought up to the current schema, unsupported keys)
Resolver = Callable[[dict], tuple[dict, list[str]]]


def _no_resolver(flags: dict) -> tuple[dict, list[str]]:
    return dict(flags), []


def _migrate_v0_to_v1(payload: Any) -> list:
    # v0 was the bare list; anything else means a file we can't interpret.
    return payload if isinstance(payload, list) else []


def _migrate_v1_to_v2(payload: Any) -> list:
    items = payload if isinstance(payload, list) else []
    return [{**p, "updated_at": p.get("updated_at")} for p in items if isinstance(p, dict)]


MIGRATIONS = {0: _migrate_v0_to_v1, 1: _migrate_v1_to_v2}


class PresetStore:
    def __init__(self, path: Path, resolve: Resolver = _no_resolver) -> None:
        self._store = JsonDocumentStore(
            path, key="presets", version=FORMAT_VERSION, migrations=MIGRATIONS, empty=list,
        )
        self._resolve = resolve

    def _normalize_entry(self, p: dict) -> dict:
        flags, unsupported = self._resolve(p.get("flags") or {})
        return {
            "name": p["name"],
            "model_id": p["model_id"],
            "flags": flags,
            "updated_at": p.get("updated_at"),
            "unsupported": unsupported,
        }

    @property
    def path(self) -> Path:
        return self._store.path

    def adopt_legacy_file(self, candidates: Iterable[Path]) -> Optional[Path]:
        return self._store.adopt_legacy_file(candidates)

    def list(self) -> list[dict]:
        return [self._normalize_entry(p) for p in self._store.load() if isinstance(p, dict) and "name" in p]

    def upsert(self, name: str, model_id: str, flags: dict) -> dict:
        preset = self._normalize_entry(
            {"name": name, "model_id": model_id, "flags": flags, "updated_at": time.time()}
        )
        # `unsupported` depends on the installed binary; it is derived on
        # every read, never written.
        stored = {k: v for k, v in preset.items() if k != "unsupported"}
        self._store.update(lambda items: [p for p in items if p.get("name") != name] + [stored])
        return preset

    def delete(self, name: str) -> bool:
        removed = {"any": False}

        def drop(items: list) -> list:
            remaining = [p for p in items if p.get("name") != name]
            removed["any"] = len(remaining) != len(items)
            return remaining

        self._store.update(drop)
        return removed["any"]
