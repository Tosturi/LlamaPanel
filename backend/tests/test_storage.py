import json

import pytest

from app import __version__
from app.storage import JsonDocumentStore, NewerFormatError


def _store(path, version=2, migrations=None, empty=list) -> JsonDocumentStore:
    if migrations is None:
        migrations = {
            0: lambda payload: payload if isinstance(payload, list) else [],
            1: lambda payload: [{**p, "extra": True} for p in payload],
        }
    return JsonDocumentStore(path, key="items", version=version, migrations=migrations, empty=empty)


@pytest.fixture
def path(tmp_path):
    return tmp_path / "items.json"


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_load_returns_empty_when_file_missing(path):
    assert _store(path).load() == []
    assert not path.exists()


def test_save_writes_versioned_wrapper_with_app_version(path):
    _store(path).save([{"a": 1}])

    assert _read(path) == {"version": 2, "app_version": __version__, "items": [{"a": 1}]}


def test_update_is_read_modify_write(path):
    store = _store(path)
    store.save([1])

    result = store.update(lambda items: items + [2])

    assert result == [1, 2]
    assert store.load() == [1, 2]


def test_bare_legacy_file_is_migrated_through_every_step(path):
    path.write_text(json.dumps([{"name": "old"}]), encoding="utf-8")

    assert _store(path).load() == [{"name": "old", "extra": True}]
    assert _read(path)["version"] == 2


def test_migration_keeps_a_backup_of_the_old_file(path):
    path.write_text(json.dumps({"version": 1, "items": [{"name": "p"}]}), encoding="utf-8")

    _store(path).load()

    backup = path.with_name("items.json.v1.bak")
    assert _read(backup) == {"version": 1, "items": [{"name": "p"}]}


def test_migration_persists_the_result_so_it_runs_once(path):
    calls = []
    migrations = {0: lambda p: p, 1: lambda p: (calls.append(1), p)[1]}
    path.write_text(json.dumps({"version": 1, "items": []}), encoding="utf-8")

    store = _store(path, migrations=migrations)
    store.load()
    store.load()

    assert calls == [1]


def test_current_version_file_is_not_touched(path):
    _store(path).save([1])
    before = path.stat().st_mtime_ns
    _store(path).load()
    assert path.stat().st_mtime_ns == before
    assert list(path.parent.iterdir()) == [path]


def test_newer_format_is_refused_and_left_intact(path):
    original = {"version": 99, "app_version": "9.9.9", "items": [{"future": True}]}
    path.write_text(json.dumps(original), encoding="utf-8")
    store = _store(path)

    with pytest.raises(NewerFormatError) as exc:
        store.load()
    with pytest.raises(NewerFormatError):
        store.update(lambda items: [])

    assert exc.value.found == 99 and exc.value.supported == 2
    assert "99" in str(exc.value)
    assert _read(path) == original


def test_corrupt_file_is_quarantined_not_overwritten(path):
    path.write_text("{not json", encoding="utf-8")

    assert _store(path).load() == []

    assert not path.exists()
    quarantined = [p for p in path.parent.iterdir() if ".corrupt-" in p.name]
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == "{not json"


def test_missing_migration_step_is_a_programming_error(path):
    with pytest.raises(ValueError):
        _store(path, version=3)


def test_adopt_legacy_file_copies_first_existing_candidate(tmp_path, path):
    old_a = tmp_path / "old-a" / "items.json"
    old_b = tmp_path / "old-b" / "items.json"
    old_b.parent.mkdir()
    old_b.write_text("[1]", encoding="utf-8")
    store = _store(path)

    assert store.adopt_legacy_file([old_a, old_b]) == old_b
    assert path.read_text(encoding="utf-8") == "[1]"
    assert old_b.exists()  # copied, not moved


def test_adopt_legacy_file_is_noop_when_own_file_exists(tmp_path, path):
    old = tmp_path / "old" / "items.json"
    old.parent.mkdir()
    old.write_text("[1]", encoding="utf-8")
    store = _store(path)
    store.save([2])

    assert store.adopt_legacy_file([old]) is None
    assert store.load() == [2]


def test_adopt_legacy_file_ignores_candidate_equal_to_own_path(path):
    assert _store(path).adopt_legacy_file([path]) is None
    assert not path.exists()


def test_save_leaves_no_temp_files_behind(path):
    store = _store(path)
    store.save([1])
    store.save([2])
    assert [p.name for p in path.parent.iterdir()] == ["items.json"]
