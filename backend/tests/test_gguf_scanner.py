import os
from pathlib import Path

import app.gguf_scanner as scanner


def _touch(path: Path) -> Path:
    path.write_bytes(b"")
    return path


def test_scan_missing_directory_returns_empty_list(tmp_path):
    assert scanner.scan(tmp_path / "does-not-exist") == []


def test_scan_empty_directory_returns_empty_list(tmp_path):
    assert scanner.scan(tmp_path) == []


def test_scan_groups_split_model_parts(tmp_path, monkeypatch):
    monkeypatch.setattr(scanner, "_read_gguf_metadata", lambda p: {})
    _touch(tmp_path / "big-model-00001-of-00002.gguf")
    _touch(tmp_path / "big-model-00002-of-00002.gguf")

    models = scanner.scan(tmp_path)

    assert len(models) == 1
    model = models[0]
    assert model.is_split is True
    assert model.id == "big-model"
    assert [p.filename for p in model.parts] == [
        "big-model-00001-of-00002.gguf",
        "big-model-00002-of-00002.gguf",
    ]
    assert model.entry_path.endswith("big-model-00001-of-00002.gguf")


def test_scan_treats_non_split_file_as_single_model(tmp_path, monkeypatch):
    monkeypatch.setattr(scanner, "_read_gguf_metadata", lambda p: {})
    _touch(tmp_path / "solo-model.gguf")

    models = scanner.scan(tmp_path)

    assert len(models) == 1
    assert models[0].is_split is False
    assert models[0].id == "solo-model"


def test_scan_prefers_embedded_name_over_filename(tmp_path, monkeypatch):
    monkeypatch.setattr(scanner, "_read_gguf_metadata", lambda p: {"name": "Fancy Name"})
    _touch(tmp_path / "raw-filename.gguf")

    models = scanner.scan(tmp_path)

    assert models[0].display_name == "Fancy Name"


def test_scan_falls_back_to_filename_when_no_embedded_name(tmp_path, monkeypatch):
    monkeypatch.setattr(scanner, "_read_gguf_metadata", lambda p: {})
    _touch(tmp_path / "raw-filename.gguf")

    models = scanner.scan(tmp_path)

    assert models[0].display_name == "raw-filename"


def test_scan_sorts_models_by_display_name_case_insensitively(tmp_path, monkeypatch):
    monkeypatch.setattr(scanner, "_read_gguf_metadata", lambda p: {})
    _touch(tmp_path / "Zeta.gguf")
    _touch(tmp_path / "alpha.gguf")

    models = scanner.scan(tmp_path)

    assert [m.id for m in models] == ["alpha", "Zeta"]


def test_metadata_is_cached_until_the_file_changes(tmp_path, monkeypatch):
    calls = []

    def fake_read(path):
        calls.append(path)
        return {"name": f"call-{len(calls)}"}

    monkeypatch.setattr(scanner, "_read_gguf_metadata", fake_read)
    f = _touch(tmp_path / "model.gguf")

    first = scanner.scan(tmp_path)[0].display_name
    second = scanner.scan(tmp_path)[0].display_name
    assert first == second == "call-1"
    assert len(calls) == 1

    new_mtime = f.stat().st_mtime + 5
    os.utime(f, (new_mtime, new_mtime))

    third = scanner.scan(tmp_path)[0].display_name
    assert third == "call-2"
    assert len(calls) == 2
