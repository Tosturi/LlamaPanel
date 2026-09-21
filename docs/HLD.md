# HLD: LlamaPanel architecture

[Documentation](README.md) · [Server instances](instances.md)

## Purpose and boundaries

LlamaPanel manages local `llama-server` processes on a machine with a llama.cpp
binary and GGUF files. It provides configuration, process controls and logs.
External clients connect directly to the chosen instance's API; the panel
does not proxy inference requests.

## Components

| Component | Responsibility |
|---|---|
| `run.py` | Prepare `.venv`, load configuration and start Uvicorn |
| `backend/app/main.py` | FastAPI factory and application object lifecycle |
| `backend/app/settings.py` | Immutable `Settings`; precedence: CLI → INI → environment → defaults |
| `backend/app/instances.py` | `InstanceRegistry`: configurations, port reservations and process recovery |
| `backend/app/process_manager.py` | Per-instance `ProcessManager`: process, state, restart queue and logs |
| `backend/app/llama_client.py` | HTTP checks of instance `/health` and `/slots` |
| `backend/app/discovery.py` | External process discovery for legacy single-server compatibility |
| `backend/app/gguf_scanner.py` | Scan models and LoRA adapters; read selected GGUF metadata |
| `backend/app/introspection.py` | `BinaryInspector`: read and cache `--version` and `--help` |
| `backend/app/flags.py` | `FlagCatalog`: form schema, key resolution, argument building and parsing |
| `backend/app/presets.py` | Shared preset library |
| `backend/app/storage.py` | Versioned JSON documents, migrations and atomic writes |
| `backend/app/deps.py` | Router access to application objects and the selected manager |
| `frontend/src/App.tsx` | Instance overview and workspaces with configuration, status and logs |

Objects are created during `lifespan` and exposed through `app.state`.
`ManagerDep` selects a manager by `instance_id`, falling back to `default`
when omitted. Model and preset libraries, the flag schema and binary are shared.

## Instance lifecycle

Each instance has its own PID, port, flags, restart queue and log file.
After launch it remains `starting` until `/health` confirms readiness.
`running` means the server is ready; an unexpected process exit sets `crashed`.

If `/slots` confirms active generation, a restart is queued until it finishes.
If activity cannot be determined, an immediate restart is allowed. Queues and
cancellation apply only to the selected instance.

Closing the panel leaves processes running but cancels queued restarts.
On the next launch, the registry checks saved PIDs, process creation times and
executable identity before reattaching. Creation-time checks also protect stop
operations on adopted processes against PID reuse. Stopped instances are not
started automatically.

## Flags and presets

The form schema comes from the installed binary's `--help`. `CURATED` supplies
labels, core groups and stable keys; `HIDDEN` excludes panel-managed parameters.
If the binary is unavailable, the panel uses
`backend/app/snapshots/llama-server-help.txt`.

The form stores only explicit overrides. `build_args` passes them even when
they match documented defaults. Empty values are omitted; boolean pairs use
the appropriate `--x` or `--no-x` spelling, and repeatable flags are emitted
once per item. The panel supplies the model and port. The port belongs to the
instance and is not replaced by a preset's port.

`parse_args` recovers flags from an adopted process's command line. Older
presets retain their values because it is impossible to tell which were
entered manually. See [configuration and storage](configuration.md) for key
resolution and migrations.

## Models and interface

The main model name comes from its filename without `.gguf`; split GGUF files
use the shared prefix without the part number. `general.name` is stored
separately and shown in Models details alongside architecture, quantization,
context size and files.

REST carries state and configuration; WebSocket carries the selected
instance's logs. Frontend types are generated from OpenAPI. Drafts survive
navigation between instances in the current browser tab; Save configuration,
Start and Apply & restart persist them.

Inside a workspace, Server returns to configuration while Models, LoRA library
and Presets keep the selected instance. All servers returns to the list.
Card controls start saved configurations, stop individual instances and open
their logs without discarding workspace drafts.

## Constraints

Use one panel process per data directory. Ports are reserved across saved
instances, including stopped ones. A pre-launch port check cannot prevent an
external process from claiming the port immediately afterwards. The panel
does not allocate GPU memory: available resources limit concurrent models.
