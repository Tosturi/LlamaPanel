"""Versioned JSON documents on disk, with forward migrations.

Every persisted file is wrapped as

    {"version": <int>, "app_version": "<LlamaPanel version>", "<key>": <payload>}

so a later release can change the payload shape and still read what an
older release wrote. The rules that make upgrades (and downgrades) safe:

- A file with an *older* version is migrated forward on first read, one
  step at a time (migrations[found] -> found+1 -> ...). Before touching it
  a copy is kept next to it as ``<name>.v<found>.bak`` so a bad migration
  is never a data loss.
- A file with a *newer* version than this code knows is refused with
  NewerFormatError and never overwritten - downgrading LlamaPanel must not
  destroy state written by the newer one.
- A file that is not valid JSON at all is moved aside as
  ``<name>.corrupt-<timestamp>`` and the store starts empty, so the
  user's data is still recoverable by hand.
- Writes are atomic (temp file + fsync + os.replace) so a crash mid-write
  leaves the previous document intact.

The store is deliberately generic: it knows nothing about presets. That is
what lets a second entity (e.g. UI settings) reuse it later without
copy-pasting the migration/backup logic.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Iterable, Optional

from app import __version__

Migration = Callable[[Any], Any]


class StoreError(Exception):
    pass


class NewerFormatError(StoreError):
    """The file on disk was written by a newer LlamaPanel than this one."""

    def __init__(self, path: Path, found: int, supported: int) -> None:
        self.path = path
        self.found = found
        self.supported = supported
        super().__init__(
            f"{path} has format version {found}, but this LlamaPanel {__version__} only "
            f"understands up to {supported}. Upgrade LlamaPanel, or move the file away to start fresh."
        )


class JsonDocumentStore:
    def __init__(
        self,
        path: Path,
        *,
        key: str,
        version: int,
        migrations: dict[int, Migration],
        empty: Callable[[], Any],
    ) -> None:
        """
        path:       the JSON file.
        key:        name of the payload field inside the wrapper document.
        version:    the format version this code writes.
        migrations: {from_version: fn(payload) -> payload} for every
                    from_version in range(0, version). Version 0 means "a
                    bare, unwrapped file written before versioning existed".
        empty:      factory for the payload when the file does not exist.
        """
        missing = [v for v in range(version) if v not in migrations]
        if missing:
            raise ValueError(f"{path.name}: no migration registered for version(s) {missing}")
        self._path = path
        self._key = key
        self._version = version
        self._migrations = migrations
        self._empty = empty
        self._lock = Lock()

    @property
    def path(self) -> Path:
        return self._path

    # --- public API ---------------------------------------------------------

    def load(self) -> Any:
        with self._lock:
            return self._load_locked()

    def save(self, payload: Any) -> None:
        with self._lock:
            self._save_locked(payload)

    def update(self, fn: Callable[[Any], Any]) -> Any:
        """Read-modify-write under the lock: fn(current) -> new payload,
        which is persisted and returned."""
        with self._lock:
            payload = fn(self._load_locked())
            self._save_locked(payload)
            return payload

    def adopt_legacy_file(self, candidates: Iterable[Path]) -> Optional[Path]:
        """If our own file does not exist yet, copy the first existing
        candidate into place. Used once at startup so state written by an
        older release into a different location is picked up instead of
        silently starting from scratch. Returns the adopted source, if any."""
        with self._lock:
            if self._path.exists():
                return None
            for candidate in candidates:
                try:
                    same = candidate.resolve() == self._path.resolve()
                except OSError:
                    same = False
                if same or not candidate.is_file():
                    continue
                self._path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidate, self._path)
                print(f"Copied existing {candidate} to {self._path}", flush=True)
                return candidate
        return None

    # --- internals ----------------------------------------------------------

    def _load_locked(self) -> Any:
        if not self._path.exists():
            return self._empty()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            moved = self._quarantine()
            print(f"WARNING: {self._path} is not valid JSON ({exc}); moved it to {moved}", flush=True)
            return self._empty()

        found, payload = self._unwrap(raw)
        if found > self._version:
            raise NewerFormatError(self._path, found, self._version)
        if found < self._version:
            payload = self._migrate(found, payload)
        return payload

    def _unwrap(self, raw: Any) -> tuple[int, Any]:
        if isinstance(raw, dict) and isinstance(raw.get("version"), int) and not isinstance(raw["version"], bool):
            return raw["version"], raw.get(self._key)
        return 0, raw  # pre-versioning file: the payload itself

    def _migrate(self, found: int, payload: Any) -> Any:
        backup = self._path.with_name(f"{self._path.name}.v{found}.bak")
        shutil.copy2(self._path, backup)
        for step in range(found, self._version):
            payload = self._migrations[step](payload)
        self._save_locked(payload)
        print(
            f"Migrated {self._path} from format version {found} to {self._version} (backup: {backup.name})",
            flush=True,
        )
        return payload

    def _quarantine(self) -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = self._path.with_name(f"{self._path.name}.corrupt-{stamp}")
        n = 1
        while target.exists():
            target = self._path.with_name(f"{self._path.name}.corrupt-{stamp}-{n}")
            n += 1
        os.replace(self._path, target)
        return target

    def _save_locked(self, payload: Any) -> None:
        document = {"version": self._version, "app_version": __version__, self._key: payload}
        text = json.dumps(document, indent=2, ensure_ascii=False)
        target = self._path
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=target.parent, prefix=target.name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, target)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
