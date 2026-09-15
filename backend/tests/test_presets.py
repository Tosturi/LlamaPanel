import json

import pytest

from app import __version__
from app.presets import FORMAT_VERSION, PresetStore
from app.storage import NewerFormatError


@pytest.fixture
def store(tmp_path) -> PresetStore:
    return PresetStore(tmp_path / "presets.json")


def _read(store):
    return json.loads(store.path.read_text(encoding="utf-8"))


def test_list_empty_when_file_missing(store):
    assert store.list() == []


def test_upsert_then_list_roundtrip(store):
    saved = store.upsert("p1", "model-a", {"ctx_size": 4096})

    assert saved["name"] == "p1"
    assert saved["model_id"] == "model-a"
    assert saved["flags"] == {"ctx_size": 4096}
    assert isinstance(saved["updated_at"], float)
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
    # ... and keeps the broken file around for manual recovery.
    assert any(".corrupt-" in p.name for p in store.path.parent.iterdir())


def test_save_writes_versioned_wrapper(store):
    store.upsert("p1", "model-a", {})

    data = _read(store)
    assert data["version"] == FORMAT_VERSION
    assert data["app_version"] == __version__
    assert [p["name"] for p in data["presets"]] == ["p1"]


def test_load_migrates_v0_bare_list_format(store):
    store.path.write_text(json.dumps([{"name": "old", "model_id": "m", "flags": {"ctx_size": 1}}]), encoding="utf-8")

    items = store.list()

    assert items == [{"name": "old", "model_id": "m", "flags": {"ctx_size": 1}, "updated_at": None}]
    assert _read(store)["version"] == FORMAT_VERSION
    assert store.path.with_name("presets.json.v0.bak").exists()


def test_load_migrates_v1_wrapper_format(store):
    v1 = {"version": 1, "presets": [{"name": "old", "model_id": "m", "flags": {}}]}
    store.path.write_text(json.dumps(v1), encoding="utf-8")

    items = store.list()

    assert [p["name"] for p in items] == ["old"]
    assert items[0]["updated_at"] is None
    assert _read(store)["version"] == FORMAT_VERSION
    assert json.loads(store.path.with_name("presets.json.v1.bak").read_text(encoding="utf-8")) == v1


def test_newer_file_raises_instead_of_being_overwritten(store):
    store.path.write_text(json.dumps({"version": FORMAT_VERSION + 1, "presets": []}), encoding="utf-8")

    with pytest.raises(NewerFormatError):
        store.list()
    with pytest.raises(NewerFormatError):
        store.upsert("p", "m", {})

    assert _read(store)["version"] == FORMAT_VERSION + 1


def test_flags_are_normalized_on_read(store):
    # A value saved as text by an older UI comes back as the declared type.
    store.path.write_text(
        json.dumps([{"name": "p", "model_id": "m", "flags": {"ctx_size": "8192", "no_kv_offload": "true"}}]),
        encoding="utf-8",
    )
    assert store.list()[0]["flags"] == {"ctx_size": 8192, "no_kv_offload": True}


def test_unknown_flags_survive_a_roundtrip(store):
    store.upsert("p", "m", {"from_the_future": "x", "ctx_size": 1})
    assert store.list()[0]["flags"] == {"from_the_future": "x", "ctx_size": 1}


def test_entries_without_a_name_are_skipped(store):
    store.path.write_text(json.dumps([{"model_id": "m"}, "junk", {"name": "ok", "model_id": "m"}]), encoding="utf-8")
    assert [p["name"] for p in store.list()] == ["ok"]


def test_adopt_legacy_file_copies_old_presets(tmp_path, store):
    legacy = tmp_path / "old" / "presets.json"
    legacy.parent.mkdir()
    legacy.write_text(json.dumps([{"name": "old", "model_id": "m", "flags": {}}]), encoding="utf-8")

    assert store.adopt_legacy_file([tmp_path / "nope" / "presets.json", legacy]) == legacy
    assert [p["name"] for p in store.list()] == ["old"]


def test_save_creates_missing_parent_directory(tmp_path):
    store = PresetStore(tmp_path / "nested" / "dir" / "presets.json")
    store.upsert("p1", "model-a", {})
    assert store.path.exists()


def test_save_leaves_no_temp_files_behind(store):
    store.upsert("p1", "model-a", {})
    store.delete("p1")

    assert [p.name for p in store.path.parent.iterdir()] == ["presets.json"]
