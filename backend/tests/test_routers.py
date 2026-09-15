from fastapi.testclient import TestClient

from app import __version__, config
from app.main import app

client = TestClient(app)


def test_health_endpoint_reports_version():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["version"] != "unknown"


def test_flags_endpoint_returns_the_flag_schema():
    resp = client.get("/api/server/flags")
    assert resp.status_code == 200
    keys = [f["key"] for f in resp.json()]
    assert "ctx_size" in keys
    assert "flash_attn" in keys


def test_models_endpoint_lists_scanned_gguf_files(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    (tmp_path / "solo.gguf").write_bytes(b"")

    resp = client.get("/api/models")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == "solo"


def test_models_endpoint_empty_when_directory_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "does-not-exist")

    resp = client.get("/api/models")

    assert resp.status_code == 200
    assert resp.json() == []


def test_presets_crud_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PRESETS_FILE", tmp_path / "presets.json")

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

    assert client.get("/api/presets").json() == []


def test_save_preset_rejects_name_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PRESETS_FILE", tmp_path / "presets.json")

    resp = client.put(
        "/api/presets/name-in-url",
        json={"name": "different-name", "model_id": "m1", "flags": {}},
    )
    assert resp.status_code == 400


def test_delete_missing_preset_returns_404(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PRESETS_FILE", tmp_path / "presets.json")

    resp = client.delete("/api/presets/does-not-exist")
    assert resp.status_code == 404


def test_start_server_rejects_unknown_model(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)

    resp = client.post("/api/server/start", json={"model_id": "no-such-model", "flags": {}})
    assert resp.status_code == 404


def test_restart_rejects_when_server_not_running(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    (tmp_path / "solo.gguf").write_bytes(b"")

    resp = client.post("/api/server/restart", json={"model_id": "solo", "flags": {}})
    assert resp.status_code == 409
