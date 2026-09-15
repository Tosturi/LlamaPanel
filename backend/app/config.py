import os
from pathlib import Path


def _env(name: str, *legacy: str, default: str) -> str:
    """Read LLAMAPANEL_<name>, falling back to older env var spellings that
    predate the unified prefix so existing setups keep working."""
    for key in (f"LLAMAPANEL_{name}", *legacy):
        value = os.environ.get(key)
        if value:
            return value
    return default


MODELS_DIR = Path(_env("MODELS_DIR", "LLAMA_MODELS_DIR", default="./models")).resolve()
LLAMA_SERVER_BIN = _env("SERVER_BIN", "LLAMA_SERVER_BIN", default="llama-server")
LOG_BUFFER_SIZE = int(_env("LOG_BUFFER_SIZE", "LOG_BUFFER_SIZE", default="2000"))

DATA_DIR = Path(_env("DATA_DIR", default="./data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

PRESETS_FILE = DATA_DIR / "presets.json"
# llama-server's stdout/stderr always redirect here (not to a PIPE). This
# means logs survive a panel restart: if llama-server is left running as an
# orphan, its fd still points at this file and we can just keep tailing it.
LOG_FILE = DATA_DIR / "llama-server.log"
