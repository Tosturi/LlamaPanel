# Multiple llama-server instances

[Documentation](README.md) · [Architecture](HLD.md)

## Using the interface

The **Servers** page lists independent `llama-server` instances. Click
**Create server** and choose a name and a unique API port.

Each card provides these controls:

- **Open server** opens the instance's configuration.
- **Start** launches its saved model and flags. Save a configuration first;
  unsaved workspace edits are not used by this shortcut.
- **Stop** stops that instance without affecting the others.
- **Logs** opens that instance's live logs directly, including when it is stopped.

Start and Stop show progress and are disabled when unavailable. Errors appear
on the affected card. Other instances can still be controlled independently.

Inside an instance, the main tabs are **Server**, **Models**, **LoRA library**
and **Presets**. **Server** returns to that instance's configuration.
**All servers**, below the main navigation, returns to the instance list from
any tab. Reopening an instance keeps its unsaved edits.

- **Save configuration** saves without starting or restarting the server.
- **Start** and **Apply & restart** in the workspace also save the requested configuration.
- Drafts survive switching between instances in the current browser tab;
  reloading the page restores only saved settings.
- Models and presets are shared. Loading a preset does not change the instance's
  port; the panel passes that port explicitly.

Each instance has its own process, readiness checks, restart queue and log stream.
Stopping one instance does not stop the others.

## Runtime selection

Configure the default executable and named alternatives in
**Settings → llama-server runtimes**, then choose a build for each instance in
**Server → Overview → Runtime**. Existing and new instances use the default
runtime until changed.

Selecting a runtime saves the choice immediately and re-reads `--version` and
`--help` to update the flag form and preset compatibility. It does not restart
the running server; the selected build is used on the next start or restart.
Already queued restarts keep their captured executable and arguments. See
[multiple llama-server builds](configuration.md#multiple-llama-server-builds)
for details.

## Ports and deletion

A saved instance reserves its port even while stopped. Startup is rejected if
an external process occupies that port. Stop the instance before changing its
port or deleting it.

Deleting a configuration does not delete model files, presets or logs. The
`default` instance remains for compatibility with older API clients and cannot
be deleted through the UI or API.

## Storage and recovery

Configurations and process identity records are stored in `instances.json` in
the [panel's data directory](configuration.md). Additional instances write logs
to `instances/<id>/llama-server.log`; `default` keeps the original
`llama-server.log` at the data directory root.

Closing the panel leaves server processes running. On the next launch, recorded
PIDs are checked against process creation times and executable identity before
reattachment. Stopped instances are not started automatically. Queued restarts
are cancelled when the panel shuts down.

Use one panel process per data directory. Running multiple models requires
enough RAM/VRAM; the panel does not manage GPU memory allocation.

## API

| Method and path | Purpose |
|---|---|
| `GET /api/instances` | List configurations and statuses |
| `POST /api/instances` | Create an instance |
| `PUT /api/instances/{id}` | Save a configuration |
| `DELETE /api/instances/{id}` | Delete a stopped instance |
| `GET /api/instances/{id}/runtime` | Read the selected runtime ID, binary information and flag schema |
| `PUT /api/instances/{id}/runtime` | Select and save a runtime, re-probe its binary and return the refreshed schema |

The `/api/server/status`, `/api/server/start`, `/api/server/stop`,
`/api/server/restart`, `/api/server/restart/cancel` routes and the
`/api/server/logs` WebSocket accept `?instance_id=<id>`. Omitting it selects
the `default` instance.

`GET /api/server/flags` and `GET /api/server/binary` also accept
`?instance_id=<id>` and resolve against that instance's selected runtime.
Omitting it selects the `default` instance, which may itself use a named runtime.
`GET /api/server/binary?instance_id=<id>&refresh=true` forces a fresh binary probe.

`PUT /api/instances/{id}/runtime` accepts `{"runtime_id": "<runtime-id>"}`.
Both runtime endpoints return `runtime_id`, `binary` and `flags`. Selecting a
runtime changes future launches without stopping the current process.
