"""Runtime configuration as one explicit, immutable object.

Nothing here reads the environment at import time and nothing touches the
filesystem. run.py builds a Settings (CLI > config.ini > env > defaults) and
hands it to create_app(); tests build one pointing at tmp_path. The only
place the environment is consulted is Settings.from_env(), which is called
by whoever owns the process boundary (run.py, or create_app() when uvicorn
imports the app by string for --reload).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Repository / install root: the directory holding run.py, VERSION, frontend/.
ROOT = Path(__file__).resolve().parents[2]

ENV_PREFIX = "LLAMAPANEL_"
APP_NAME = "LlamaPanel"


def _env(name: str, *legacy: str) -> str | None:
    """Read LLAMAPANEL_<name>, falling back to older env var spellings that
    predate the unified prefix so existing setups keep working."""
    for key in (f"{ENV_PREFIX}{name}", *legacy):
        value = os.environ.get(key)
        if value:
            return value
    return None


def default_data_dir() -> Path:
    """Per-user state directory, deliberately *outside* the install tree.

    Presets and the llama-server log used to live in data/ next to run.py,
    which meant unpacking a new release into a fresh folder (or deleting the
    old one) silently lost every preset. The OS-conventional per-user
    location survives reinstalls and is the same for every LlamaPanel
    checkout on the machine. Only environment variables are consulted; the
    directory is created later by Settings.ensure_dirs().
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_NAME.lower()


def default_legacy_data_dirs() -> tuple[Path, ...]:
    """Where older releases kept their state. On first start with an empty
    data_dir, presets found in one of these are copied over (see
    create_app's lifespan) so an upgrade never starts from scratch."""
    candidates = [ROOT / "data", ROOT / "backend" / "data", Path.cwd() / "data"]
    unique: list[Path] = []
    for c in candidates:
        if c not in unique:
            unique.append(c)
    return tuple(unique)


@dataclass(frozen=True)
class Settings:
    models_dir: Path = ROOT / "models"
    server_bin: str = "llama-server"
    data_dir: Path = field(default_factory=default_data_dir)
    log_buffer_size: int = 2000
    frontend_dist: Path = ROOT / "frontend" / "dist"
    # Directories whose presets.json is adopted when data_dir has none yet.
    # Tests pass () so they never pick up state from the developer's machine.
    legacy_data_dirs: tuple[Path, ...] = field(default_factory=default_legacy_data_dirs)

    @property
    def presets_file(self) -> Path:
        return self.data_dir / "presets.json"

    @property
    def legacy_presets_files(self) -> tuple[Path, ...]:
        return tuple(d / "presets.json" for d in self.legacy_data_dirs)

    @property
    def log_file(self) -> Path:
        # llama-server's stdout/stderr always redirect here (not to a PIPE).
        # Logs therefore survive a panel restart: an orphaned llama-server
        # keeps writing to this file and the new panel just tails it.
        return self.data_dir / "llama-server.log"

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls()
        models_dir = _env("MODELS_DIR", "LLAMA_MODELS_DIR")
        data_dir = _env("DATA_DIR")
        return cls(
            models_dir=Path(models_dir).resolve() if models_dir else defaults.models_dir,
            server_bin=_env("SERVER_BIN", "LLAMA_SERVER_BIN") or defaults.server_bin,
            data_dir=Path(data_dir).resolve() if data_dir else defaults.data_dir,
            log_buffer_size=int(_env("LOG_BUFFER_SIZE") or defaults.log_buffer_size),
        )

    def to_env(self) -> dict[str, str]:
        """Inverse of from_env(): the variables a child process needs to
        rebuild an equal Settings. Used only for uvicorn --reload, which has
        to import the app by string and can't be handed an object."""
        return {
            f"{ENV_PREFIX}MODELS_DIR": str(self.models_dir),
            f"{ENV_PREFIX}SERVER_BIN": self.server_bin,
            f"{ENV_PREFIX}DATA_DIR": str(self.data_dir),
            f"{ENV_PREFIX}LOG_BUFFER_SIZE": str(self.log_buffer_size),
        }

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
