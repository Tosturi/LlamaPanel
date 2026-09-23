# Application updates

[Documentation](README.md)

## Using the updater

Start a release installation with `python run.py`, open the panel using
`localhost` or a loopback IP on the same machine, then open **Settings → Updates**.
**Check for updates** shows the latest stable release and its release notes.
Save any edited settings, close the file picker and click **Update & restart**.
The page shows download, preparation and restart progress, then reloads after a
successful update. Downloads and dependency installation need internet access.
The installation directory must be writable, with room for another copy of the
application and its Python environment. Node.js is not needed.

The first release containing this updater must be installed manually. Releases
without `release.json`, Git checkouts, `--reload` and direct Uvicorn launches do
not support in-app installation. Git checkouts can still check release notes;
update them with Git and rebuild the frontend as described in the README.

Only newer stable `x.y.z` releases from `Tosturi/LlamaPanel` are offered. There is
no background installation or automatic version bump. The updater checks the
downloaded ZIP against the release's SHA-256 file and validates its layout,
version, updater protocol and minimum Python version before starting it.
The checksum detects corruption; the trust source remains the official GitHub
repository and its release workflow.

## Restart and data

The panel restarts; running `llama-server` processes keep running and the new
panel recovers them from the existing instance checkpoints. Queued restarts are
cancelled during panel shutdown, just as with a normal panel restart.
Models, LoRAs, the `llama-server` binary, logs and saved settings stay in their
existing locations. Updating LlamaPanel does not update llama.cpp.

Keep launching **the original installation's `run.py`**. It selects the active
version automatically. Do not move or delete that installation after updating:
the active version and its Python environment are inside it.

## Launcher and rollback

The original launcher supervises a backend worker. Each downloaded version has
a permanent directory and its own virtual environment:

```text
.updates/versions/<id>/LlamaPanel/
```

Dependencies are installed there before the old worker exits. Existing code
and environments are never overwritten. After a clean worker shutdown, the
launcher snapshots `settings.json`, `presets.json` and `instances.json`, then
starts the candidate. A readiness response must match both the expected version
and a fresh launch token within 45 seconds. During activation, API operations
other than health/update status are temporarily unavailable.

On success, an atomic `.updates/current.json` pointer selects the new version
for subsequent launches. If startup fails, the launcher stops the candidate,
restores the JSON snapshot and starts the previous version. Preparation failures
leave the current panel running. The UI reports the failure so it can be retried.

An activation journal allows an interrupted update to be rolled back on the
next launch before saved settings are parsed. A worker lock prevents recovery
while another panel worker is still alive; stop that remaining panel process
before retrying `python run.py`. This does not require stopping llama-server.
An incomplete backup or failed restore stops recovery rather than starting
against uncertain data. Keep the installation and backups for diagnosis.

Download slots, archives, per-slot `install.log` and `data-backup` directories
are retained. There is no automatic cleanup in this version. Do not delete the
active version, its predecessor or a slot referenced by an activation journal.
Python environments contain absolute paths, so moving individual slots is not
supported.

The original supervisor uses updater protocol 1. Future releases must preserve
this protocol and `run.py` worker contract, or increment the manifest protocol
to require a manual installation. A release requiring newer Python also needs
a manual Python upgrade and installation. The updater does not install Python,
request administrator privileges or update system services/containers.
