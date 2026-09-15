#!/usr/bin/env python3
"""
Single entry point for LlamaPanel.

Meant to run ON the GPU machine that also has llama.cpp and the model files.
Requires only *some* Python (3.12+) there to bootstrap. The frontend must be
present in frontend/dist: release zips ship it pre-built, a git checkout
needs `npm run build` in frontend/ first.

Configuration, in order of precedence (highest wins):
    1. CLI flags            python run.py --port 9000
    2. config.ini            copy config.example.ini -> config.ini and edit
    3. environment variables LLAMAPANEL_MODELS_DIR, LLAMAPANEL_SERVER_BIN, ...
    4. built-in defaults     (models/ and data/ next to this file)

On first run, this also creates an isolated venv at ./.venv using whatever
Python launched this script, re-launches itself inside it, and installs
backend/requirements.txt there. On later runs both steps are a fast no-op -
it just re-execs into the existing venv and starts the server.
"""

import argparse
import configparser
import dataclasses
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
VENV_DIR = ROOT / ".venv"
CONFIG_FILE = ROOT / "config.ini"


def venv_python() -> Path:
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def ensure_venv_and_reexec() -> None:
    """Make sure we're running inside ./.venv, creating it first (with
    whatever Python launched this script) if it doesn't exist yet. If we're
    not already inside it, re-launch this same script under the venv's
    Python and exit - everything after this call then runs isolated from
    the system Python.
    """
    target = venv_python()

    try:
        already_in_venv = Path(sys.executable).resolve() == target.resolve()
    except OSError:
        already_in_venv = False

    if already_in_venv:
        return

    if not target.exists():
        print(f"No venv found - creating one at {VENV_DIR} using {sys.executable} ...", flush=True)
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])

    result = subprocess.call([str(target), str(Path(__file__).resolve()), *sys.argv[1:]])
    sys.exit(result)


def ensure_dependencies() -> None:
    try:
        import fastapi  # noqa: F401
        import gguf  # noqa: F401
        import httpx  # noqa: F401
        import psutil  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError:
        print("Installing backend dependencies into the venv...", flush=True)
        subprocess.check_call([
            sys.executable, "-m", "pip", "install",
            "-r", str(BACKEND / "requirements.txt"),
        ])
        # gguf pulls in sentencepiece transitively, which has no prebuilt
        # wheel for newer Python versions and fails building from source.
        # We only use gguf.GGUFReader for header metadata, which needs
        # nothing beyond numpy/pyyaml/tqdm (installed above) - so install it
        # with --no-deps to skip that unused, build-fragile dependency.
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "--no-deps", "gguf>=0.13",
        ])


def load_config_file() -> dict:
    """Read config.ini (if present) into a flat dict of the same keys used
    by argparse below. Missing file / missing keys just mean "no override
    from this layer" - callers still fall back to env vars / defaults.
    """
    if not CONFIG_FILE.exists():
        return {}

    parser = configparser.ConfigParser()
    parser.read(CONFIG_FILE, encoding="utf-8")
    values: dict = {}

    def get(section: str, option: str):
        return parser.get(section, option) if parser.has_section(section) and parser.has_option(section, option) else None

    if (v := get("panel", "host")) is not None:
        values["host"] = v
    if (v := get("panel", "port")) is not None:
        values["port"] = int(v)
    if (v := get("llama", "models_dir")) is not None:
        values["models_dir"] = v
    if (v := get("llama", "server_bin")) is not None:
        values["llama_bin"] = v
    if (v := get("advanced", "data_dir")) is not None:
        values["data_dir"] = v

    return values


def check_python_version() -> None:
    if sys.version_info < (3, 12):
        sys.exit(
            f"LlamaPanel requires Python 3.12+, but this is "
            f"{sys.version_info.major}.{sys.version_info.minor}. "
            f"Install a newer Python and re-run."
        )


def main() -> None:
    check_python_version()
    ensure_venv_and_reexec()  # from here on, sys.executable is ./.venv's python
    ensure_dependencies()

    file_config = load_config_file()

    parser = argparse.ArgumentParser(description="Run the LlamaPanel server.")
    parser.add_argument("--host", default=None, help="Bind address for the panel itself (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="Port for the panel itself (default: 8000)")
    parser.add_argument("--models-dir", default=None, help="Directory to scan for .gguf files")
    parser.add_argument("--llama-bin", default=None, help="Path to the llama-server binary")
    parser.add_argument("--data-dir", default=None, help="Where presets.json / llama-server.log are stored")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes (development only)")
    args = parser.parse_args()

    host = args.host or file_config.get("host") or os.environ.get("LLAMAPANEL_HOST") or "127.0.0.1"
    port = args.port or file_config.get("port") or int(os.environ.get("LLAMAPANEL_PORT", "8000"))

    if not CONFIG_FILE.exists():
        print("(no config.ini found - copy config.example.ini to set defaults; using CLI flags/env vars for now)", flush=True)

    sys.path.insert(0, str(BACKEND))
    import uvicorn
    from app import __version__
    from app.main import create_app
    from app.settings import Settings

    # Layer the config: env vars (with legacy aliases) first, then config.ini,
    # then CLI flags on top. Directory defaults inside Settings are anchored
    # to this file, not the cwd - otherwise `python /opt/LlamaPanel/run.py`
    # run from $HOME would create ~/data.
    overrides = {}
    if models_dir := (args.models_dir or file_config.get("models_dir")):
        overrides["models_dir"] = Path(models_dir).resolve()
    if llama_bin := (args.llama_bin or file_config.get("llama_bin")):
        overrides["server_bin"] = llama_bin
    if data_dir := (args.data_dir or file_config.get("data_dir")):
        overrides["data_dir"] = Path(data_dir).resolve()
    settings = dataclasses.replace(Settings.from_env(), **overrides)

    if not (settings.frontend_dist / "index.html").exists():
        print(
            "WARNING: frontend/dist not found - the web UI will not be served.\n"
            "         Download a release zip (ships pre-built), or run `npm ci && npm run build` in frontend/.",
            flush=True,
        )

    print(f"LlamaPanel {__version__} starting on http://{host}:{port}", flush=True)
    # Without timeout_graceful_shutdown, Ctrl+C hangs on "Waiting for
    # background tasks to complete" forever: the /api/server/logs websocket
    # (kept open by the UI's LogViewer) only ends when the client disconnects,
    # and uvicorn otherwise waits for that indefinitely.
    if args.reload:
        # --reload re-imports the app in a fresh process on every change, so
        # it needs an import string, not an object. Pass the resolved
        # settings through the environment for that child to pick up.
        os.environ.update(settings.to_env())
        uvicorn.run(
            "app.main:create_app", factory=True, host=host, port=port, reload=True,
            app_dir=str(BACKEND), timeout_graceful_shutdown=5,
        )
    else:
        uvicorn.run(create_app(settings), host=host, port=port, timeout_graceful_shutdown=5)


if __name__ == "__main__":
    main()
