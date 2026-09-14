from app import presets


def test_list_presets_empty_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(presets.config, "PRESETS_FILE", tmp_path / "presets.json")
    assert presets.list_presets() == []


def test_upsert_then_list_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(presets.config, "PRESETS_FILE", tmp_path / "presets.json")

    saved = presets.upsert_preset("p1", "model-a", {"ctx_size": 4096})

    assert saved == {"name": "p1", "model_id": "model-a", "flags": {"ctx_size": 4096}}
    assert presets.list_presets() == [saved]


def test_upsert_overwrites_existing_preset_with_same_name(tmp_path, monkeypatch):
    monkeypatch.setattr(presets.config, "PRESETS_FILE", tmp_path / "presets.json")

    presets.upsert_preset("p1", "model-a", {"ctx_size": 4096})
    presets.upsert_preset("p1", "model-b", {"ctx_size": 8192})

    items = presets.list_presets()
    assert len(items) == 1
    assert items[0]["model_id"] == "model-b"


def test_delete_preset_returns_false_when_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(presets.config, "PRESETS_FILE", tmp_path / "presets.json")
    assert presets.delete_preset("missing") is False


def test_delete_preset_removes_it(tmp_path, monkeypatch):
    monkeypatch.setattr(presets.config, "PRESETS_FILE", tmp_path / "presets.json")

    presets.upsert_preset("p1", "model-a", {})
    assert presets.delete_preset("p1") is True
    assert presets.list_presets() == []


def test_list_presets_tolerates_corrupt_json_file(tmp_path, monkeypatch):
    f = tmp_path / "presets.json"
    f.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(presets.config, "PRESETS_FILE", f)

    assert presets.list_presets() == []
