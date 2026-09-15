from app import __version__


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
    monkeypatch.setattr("app.routers.server.discovery.find_running_llama_server", lambda server_bin: None)

    resp = client.post("/api/server/restart", json={"model_id": "solo", "flags": {}})
    assert resp.status_code == 409


def test_status_adopts_a_discovered_process(client, settings, monkeypatch):
    settings.models_dir.mkdir()
    model_file = settings.models_dir / "solo.gguf"
    model_file.write_bytes(b"")
    seen = {}

    def fake_find(server_bin):
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
    monkeypatch.setattr("app.routers.server.discovery.find_running_llama_server", lambda server_bin: None)

    body = client.get("/api/server/status").json()

    assert body["state"] == "stopped"
    assert body["adopted"] is False


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
