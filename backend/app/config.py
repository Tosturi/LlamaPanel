import os
from pathlib import Path

MODELS_DIR = Path(os.environ.get("LLAMA_MODELS_DIR", "./models")).resolve()
LLAMA_SERVER_BIN = os.environ.get("LLAMA_SERVER_BIN", "llama-server")
LOG_BUFFER_SIZE = int(os.environ.get("LOG_BUFFER_SIZE", "2000"))

DATA_DIR = Path(os.environ.get("LLAMAPANEL_DATA_DIR", "./data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

PRESETS_FILE = DATA_DIR / "presets.json"
# llama-server's stdout/stderr always redirect here (not to a PIPE). This
# means logs survive a panel restart: if llama-server is left running as an
# orphan, its fd still points at this file and we can just keep tailing it.
LOG_FILE = DATA_DIR / "llama-server.log"
