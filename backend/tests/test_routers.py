import dataclasses
import json

from fastapi.testclient import TestClient

from app import __version__
from app.main import create_app


def test_health_endpoint_reports_version(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["version"] != "unknown"


def test_flags_endpoint_returns_the_flag_schema(client):
    resp = client.get("/api/server/flags")
    assert resp.status_code == 200
    keys = [f["key"] for f in resp.json()]
    assert "ctx_size" in keys
    assert "flash_attn" in keys


def test_models_endpoint_lists_scanned_gguf_files(client, settings):
    settings.models_dir.mkdir()
    (settings.models_dir / "solo.gguf").write_bytes(b"")

    resp = client.get("/api/models")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == "solo"


def test_models_endpoint_empty_when_directory_missing(client, settings):
    assert not settings.models_dir.exists()

    resp = client.get("/api/models")

    assert resp.status_code == 200
    assert resp.json() == []


def test_loras_endpoint_lists_adapters_from_the_loras_folder(client, settings):
    (settings.models_dir / "loras").mkdir(parents=True)
    (settings.models_dir / "loras" / "style.gguf").write_bytes(b"")

    resp = client.get("/api/loras")

    assert resp.status_code == 200
    body = resp.json()
    assert [l["id"] for l in body] == ["loras/style"]
    assert body[0]["path"].endswith("style.gguf")


def test_lifespan_creates_the_data_dir(client, settings):
    assert settings.data_dir.is_dir()


def test_presets_crud_roundtrip(client):
    assert client.get("/api/presets").json() == []

    resp = client.put(
        "/api/presets/my-preset",
        json={"name": "my-preset", "model_id": "m1", "flags": {"ctx_size": 4096}},
    )
    assert resp.status_code == 200
    assert resp.json()["model_id"] == "m1"

    resp = client.get("/api/presets")
    assert len(resp.json()) == 1

    resp = client.delete("/api/presets/my-preset")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": "my-preset"}

    assert client.get("/api/presets").json() == []


def test_presets_are_persisted_under_data_dir(client, settings):
    client.put("/api/presets/p", json={"name": "p", "model_id": "m1", "flags": {}})
    assert settings.presets_file.exists()


def test_saved_preset_reports_updated_at_and_ignores_client_value(client):
    resp = client.put(
        "/api/presets/p",
        json={"name": "p", "model_id": "m1", "flags": {}, "updated_at": 1.0},
    )
    assert resp.status_code == 200
    assert resp.json()["updated_at"] > 1.0
    assert client.get("/api/presets").json()[0]["updated_at"] == resp.json()["updated_at"]


def test_presets_from_a_newer_version_yield_a_clear_error(client, settings):
    settings.presets_file.write_text(json.dumps({"version": 999, "presets": []}), encoding="utf-8")

    resp = client.get("/api/presets")

    assert resp.status_code == 500
    assert "999" in resp.json()["detail"]
    assert "Upgrade LlamaPanel" in resp.json()["detail"]


def test_lifespan_adopts_presets_from_legacy_data_dir(tmp_path, settings):
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    (legacy_dir / "presets.json").write_text(
        json.dumps([{"name": "old", "model_id": "m", "flags": {"ctx_size": 2048}}]), encoding="utf-8"
    )
    settings = dataclasses.replace(settings, legacy_data_dirs=(legacy_dir,))

    with TestClient(create_app(settings)) as c:
        names = [p["name"] for p in c.get("/api/presets").json()]

    assert names == ["old"]
    assert settings.presets_file.exists()
    assert (legacy_dir / "presets.json").exists()


def test_save_preset_rejects_name_mismatch(client):
    resp = client.put(
        "/api/presets/name-in-url",
        json={"name": "different-name", "model_id": "m1", "flags": {}},
    )
    assert resp.status_code == 400


def test_delete_missing_preset_returns_404(client):
    resp = client.delete("/api/presets/does-not-exist")
    assert resp.status_code == 404


def test_start_server_rejects_unknown_model(client):
    resp = client.post("/api/server/start", json={"model_id": "no-such-model", "flags": {}})
    assert resp.status_code == 404


def test_restart_rejects_when_server_not_running(client, settings, monkeypatch):
    settings.models_dir.mkdir()
    (settings.models_dir / "solo.gguf").write_bytes(b"")
    # Nothing is running, and make sure discovery doesn't adopt a real one.
    monkeypatch.setattr("app.routers.server.discovery.find_running_llama_server", lambda server_bin, schema: None)

    resp = client.post("/api/server/restart", json={"model_id": "solo", "flags": {}})
    assert resp.status_code == 409


def test_status_adopts_a_discovered_process(client, settings, monkeypatch):
    settings.models_dir.mkdir()
    model_file = settings.models_dir / "solo.gguf"
    model_file.write_bytes(b"")
    seen = {}

    def fake_find(server_bin, schema):
        seen["server_bin"] = server_bin
        return {"pid": 4242, "model_path": str(model_file), "flags": {"ctx_size": 2048}}

    monkeypatch.setattr("app.routers.server.discovery.find_running_llama_server", fake_find)
    monkeypatch.setattr("app.process_manager.psutil.pid_exists", lambda pid: True)

    body = client.get("/api/server/status").json()

    assert seen["server_bin"] == settings.server_bin
    assert body["state"] == "running"
    assert body["adopted"] is True
    assert body["pid"] == 4242
    assert body["model_id"] == "solo"
    assert body["flags"] == {"ctx_size": 2048}


def test_status_does_not_adopt_when_nothing_is_found(client, monkeypatch):
    monkeypatch.setattr("app.routers.server.discovery.find_running_llama_server", lambda server_bin, schema: None)

    body = client.get("/api/server/status").json()

    assert body["state"] == "stopped"
    assert body["adopted"] is False


def test_slow_process_scan_does_not_block_other_requests(client, monkeypatch):
    """The status poll's process scan is blocking I/O and can take seconds
    on Windows. It must run off the event loop so a concurrent request is
    served meanwhile instead of queueing behind it."""
    import threading
    import time

    scan_started = threading.Event()
    release_scan = threading.Event()

    def slow_find(server_bin, schema):
        scan_started.set()
        release_scan.wait(5)
        return None

    monkeypatch.setattr("app.routers.server.discovery.find_running_llama_server", slow_find)

    status_result = {}
    t = threading.Thread(target=lambda: status_result.update(client.get("/api/server/status").json()))
    t.start()
    assert scan_started.wait(5), "status request never reached the scan"

    started = time.perf_counter()
    health = client.get("/api/health")
    elapsed = time.perf_counter() - started

    release_scan.set()
    t.join(5)
    assert health.status_code == 200
    assert elapsed < 1.0, f"/api/health waited {elapsed:.2f}s behind the process scan"
    assert status_result["state"] == "stopped"


def test_status_does_not_adopt_if_a_start_landed_during_the_scan(client, settings, monkeypatch):
    """Discovery found an old process, but by the time it returned the user
    had started a fresh one from this panel: the fresh one wins."""
    import threading

    scan_started = threading.Event()
    release_scan = threading.Event()
    manager = client.app.state.manager

    def slow_find(server_bin, schema):
        scan_started.set()
        release_scan.wait(5)
        return {"pid": 4242, "model_path": None, "flags": {}}

    monkeypatch.setattr("app.routers.server.discovery.find_running_llama_server", slow_find)
    monkeypatch.setattr("app.process_manager.psutil.pid_exists", lambda pid: True)

    result = {}
    t = threading.Thread(target=lambda: result.update(client.get("/api/server/status").json()))
    t.start()
    assert scan_started.wait(5)
    # Simulate a Start that completed while the scan was running.
    manager._state = "starting"
    manager._pid = 1
    release_scan.set()
    t.join(5)

    assert result["pid"] != 4242
    assert result["adopted"] is False


def test_root_reports_missing_frontend(client):
    resp = client.get("/")
    assert resp.status_code == 503
    assert "npm run build" in resp.text


def test_openapi_marks_response_fields_required(client):
    """The frontend types are generated from this schema; optional-with-
    default fields must come out as required so TS doesn't get `pid?:`."""
    schema = client.get("/openapi.json").json()
    status = schema["components"]["schemas"]["StatusResponse"]
    assert set(status["required"]) >= {"state", "pid", "model_id", "busy", "restart_pending"}
