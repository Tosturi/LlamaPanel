# Configuration and storage

[Documentation](README.md) · [Installation and startup](../README.md)

Open **Settings** in the header to choose the models directory, a separate LoRA
directory, and the `llama-server` executable. When connected locally through
localhost, **Browse** opens a system selection dialog on the backend desktop
using Python's Tk support. It starts at the current path; cancelling leaves
the field unchanged. If Tk or a desktop session is unavailable, or the client
connects remotely, a modal browser lists the backend's folders and files,
including drive roots on Windows. Escape closes that modal. You can also enter
an absolute path, including a network path accessible to the backend account.
The browser never uploads files and does not create or delete them.

**Save settings** validates the directories and executable, then writes
`settings.json` beside presets and logs in the data directory. Libraries refresh
without losing server drafts. The selected binary is used for future launches;
running processes and already queued restarts retain their current configuration.
Only change the binary to a trusted llama-server build: the panel executes it
to inspect its version and supported flags.

## Multiple llama-server builds

In **Settings → llama-server runtimes**, set the default executable and use
**+ Add runtime** to add named alternatives, such as an experimental fork.
Each entry has its own executable path and Browse button. Save the settings
before choosing it in **Server → Overview → Runtime**.

The Runtime selector saves the choice for that instance immediately and probes
the selected binary again with `--version` and `--help`. The configuration form
and preset compatibility use that runtime's flags. Other instances keep their
own selection. Unsupported saved flags are retained, shown in Configuration,
and omitted from the command line until a supporting runtime is selected.

Existing instances and new instances use **Default llama-server** until changed.
Changing a runtime or its path affects future starts and restarts; it does not
stop a running process. An already queued restart keeps the executable and
arguments captured when it was queued. A runtime selected by an instance cannot
be removed until that instance selects another runtime.

The named list is persisted in `settings.json`, while each instance stores its
runtime ID in `instances.json`. Existing settings without a runtime list remain
valid. CLI/environment overrides of `server_bin` apply to the default runtime.

## Defaults and launch overrides

`settings.defaults.json` ships with platform defaults. Relative default folders
resolve against the installation directory; Windows uses `llama-server.exe`,
Linux and macOS use `llama-server`. If no full path is given, the binary is
looked up in PATH. Default model folders are not created automatically.

Precedence is **CLI flag > environment variable > saved settings.json >
settings.defaults.json**. Fields overridden at launch are marked read-only in
the UI. CLI options include `--models-dir`, `--loras-dir`, `--llama-bin`,
`--host`, `--port`, and `--data-dir`. Select the data directory at launch;
it is not moved by the Settings page. Host and port are also launch settings.

`config.ini` is no longer read and is not migrated. After upgrading, select
your paths once in Settings. Presets and instance configurations stay in place.
Settings use the same versioned, atomic JSON storage as other panel data.

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

In **Presets**, choose **Edit** on a card to rename it or change its flags and
LoRA selections. **Save changes** updates that shared preset; **Cancel** discards
the edits. Saving does not change a server's configuration or restart it: load
the edited preset when you want to use it. Names must be non-empty, and renaming
to another existing preset's name is rejected. Flags outside the selected
runtime's form are preserved unless explicitly removed or cleared.

`PATCH /api/presets/{name}?instance_id=<id>` edits an existing preset using the
selected instance's flag catalog. Send the new `name`, `model_id` and complete
`flags` in the body. Missing originals return 404; name conflicts return 409.

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
`LLAMAPANEL_HOST`, `LLAMAPANEL_PORT`, `LLAMAPANEL_MODELS_DIR`, `LLAMAPANEL_LORAS_DIR`,
`LLAMAPANEL_SERVER_BIN`, `LLAMAPANEL_DATA_DIR`, `LLAMAPANEL_LOG_BUFFER_SIZE`.
The older names `LLAMA_MODELS_DIR` and `LLAMA_SERVER_BIN` are still supported.

The application version is stored in `VERSION` and returned by `GET /api/health`.
