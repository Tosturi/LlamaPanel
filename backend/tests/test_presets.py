import json

import pytest

from app.presets import FORMAT_VERSION, PresetStore


@pytest.fixture
def store(tmp_path) -> PresetStore:
    return PresetStore(tmp_path / "presets.json")


def test_list_empty_when_file_missing(store):
    assert store.list() == []


def test_upsert_then_list_roundtrip(store):
    saved = store.upsert("p1", "model-a", {"ctx_size": 4096})

    assert saved == {"name": "p1", "model_id": "model-a", "flags": {"ctx_size": 4096}}
    assert store.list() == [saved]


def test_upsert_overwrites_existing_preset_with_same_name(store):
    store.upsert("p1", "model-a", {"ctx_size": 4096})
    store.upsert("p1", "model-b", {"ctx_size": 8192})

    items = store.list()
    assert len(items) == 1
    assert items[0]["model_id"] == "model-b"


def test_delete_returns_false_when_not_found(store):
    assert store.delete("missing") is False


def test_delete_removes_it(store):
    store.upsert("p1", "model-a", {})
    assert store.delete("p1") is True
    assert store.list() == []


def test_list_tolerates_corrupt_json_file(store):
    store.path.write_text("{not valid json", encoding="utf-8")
    assert store.list() == []


def test_save_writes_versioned_wrapper(store):
    store.upsert("p1", "model-a", {})

    data = json.loads(store.path.read_text(encoding="utf-8"))
    assert data["version"] == FORMAT_VERSION
    assert [p["name"] for p in data["presets"]] == ["p1"]


def test_load_accepts_legacy_bare_list_format(store):
    store.path.write_text(json.dumps([{"name": "old", "model_id": "m", "flags": {}}]), encoding="utf-8")
    assert [p["name"] for p in store.list()] == ["old"]


def test_save_creates_missing_parent_directory(tmp_path):
    store = PresetStore(tmp_path / "nested" / "dir" / "presets.json")
    store.upsert("p1", "model-a", {})
    assert store.path.exists()


def test_save_leaves_no_temp_files_behind(store):
    store.upsert("p1", "model-a", {})
    store.delete("p1")

    assert [p.name for p in store.path.parent.iterdir()] == ["presets.json"]
