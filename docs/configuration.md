# Configuration and storage

[Documentation](README.md) · [Installation and startup](../README.md)

Instead of editing `config.ini`, pass settings for a single run using CLI flags
(`--models-dir`, `--llama-bin`, `--host`, `--port`, `--data-dir`). Precedence is
**CLI flag > `config.ini` > environment variable > built-in default**.
`config.ini` is ignored by Git, so machine-specific paths stay local.

On the first run, the launcher:

1. Creates `./.venv` using the Python interpreter running `run.py`.
2. Re-executes itself inside that environment.
3. Installs backend dependencies with `pip install -r backend/requirements.txt`.

Nothing is installed into the system Python environment. Later launches reuse
the environment and dependencies. Open `http://127.0.0.1:8000`; use
`--host 0.0.0.0` to allow connections from other machines, then connect to
`http://<panel-machine-ip>:8000`.

If `models_dir` is unset, it defaults to `models/` next to `run.py`, independent
of the current working directory. The default `data_dir` for presets, instances
and server logs is outside the installation directory, so extracting an update
elsewhere retains access to the same data:

| OS | Path |
|---|---|
| Windows | `%LOCALAPPDATA%\LlamaPanel` |
| macOS | `~/Library/Application Support/LlamaPanel` |
| Linux | `$XDG_DATA_HOME/llamapanel` (usually `~/.local/share/llamapanel`) |

`run.py` prints the actual path at startup. If the data directory has no presets
but the legacy `data/` directory next to `run.py` does, the preset file is copied
to the new location on first launch.

## Preset storage

`presets.json` is a versioned document (`{"version": N, "app_version": ...,
"presets": [...]}`; see `backend/app/storage.py`). Format upgrades migrate it
automatically after saving a `presets.json.vN.bak` backup. Files from a newer
panel version are not overwritten; the API returns an explanatory error.
Invalid JSON is moved to `presets.json.corrupt-<timestamp>` rather than discarded.

Preset flags are resolved against the current schema on every read
(`FlagCatalog.resolve` in `backend/app/flags.py`). Keys can match any spelling
known to the installed binary (`--n-gpu-layers` and `--gpu-layers` represent
the same flag). Legacy keys such as `no_kv_offload` become `kv_offload` with
an inverted value, and changed types are converted automatically. Unknown
keys are retained and reported in `unsupported` so the UI can warn about them.
`FLAG_RENAMES` handles renames that aliases do not cover.

You can also configure settings through environment variables:
`LLAMAPANEL_HOST`, `LLAMAPANEL_PORT`, `LLAMAPANEL_MODELS_DIR`,
`LLAMAPANEL_SERVER_BIN`, `LLAMAPANEL_DATA_DIR`, `LLAMAPANEL_LOG_BUFFER_SIZE`.
The older names `LLAMA_MODELS_DIR` and `LLAMA_SERVER_BIN` are still supported.

The application version is stored in `VERSION` and returned by `GET /api/health`.
