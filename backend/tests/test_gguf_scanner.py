import os
import struct
from pathlib import Path

import app.gguf_scanner as scanner


def _touch(path: Path) -> Path:
    path.write_bytes(b"")
    return path


# --- hand-rolled GGUF writer -------------------------------------------
# Enough of the format (ggml/docs/gguf.md) to build headers with any mix of
# value types, in any key order, without depending on the `gguf` package.

def _s(text: str) -> bytes:
    raw = text.encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw


def _kv(key: str, value) -> bytes:
    """Encode one key/value pair. Python type picks the GGUF type: str ->
    string, bool -> bool, int -> uint32, float -> float32, list -> array
    (of the element type of its first item; strings or uint32)."""
    if isinstance(value, str):
        return _s(key) + struct.pack("<I", scanner._T_STRING) + _s(value)
    if isinstance(value, bool):
        return _s(key) + struct.pack("<I?", scanner._T_BOOL, value)
    if isinstance(value, int):
        return _s(key) + struct.pack("<II", scanner._T_UINT32, value)
    if isinstance(value, float):
        return _s(key) + struct.pack("<If", scanner._T_FLOAT32, value)
    if isinstance(value, list):
        if value and isinstance(value[0], str):
            body = struct.pack("<IQ", scanner._T_STRING, len(value)) + b"".join(_s(v) for v in value)
        else:
            body = struct.pack("<IQ", scanner._T_UINT32, len(value)) + struct.pack(f"<{len(value)}I", *value)
        return _s(key) + struct.pack("<I", scanner._T_ARRAY) + body
    raise TypeError(type(value))


def _gguf(pairs: list[tuple[str, object]], *, version: int = 3, magic: bytes = b"GGUF", tensors: int = 0) -> bytes:
    header = magic + struct.pack("<IQQ", version, tensors, len(pairs))
    return header + b"".join(_kv(k, v) for k, v in pairs)


REALISTIC = [
    ("general.architecture", "qwen3"),
    ("general.type", "model"),
    ("general.name", "Qwen3 9B"),
    ("general.file_type", 17),
    ("qwen3.block_count", 36),
    ("qwen3.context_length", 40960),
    ("qwen3.rope.freq_base", 1000000.0),
    ("tokenizer.ggml.model", "gpt2"),
    ("tokenizer.ggml.tokens", [f"tok{i}" for i in range(5000)]),
    ("tokenizer.ggml.token_type", [1] * 5000),
    ("tokenizer.ggml.add_bos_token", False),
]


def test_reads_the_four_displayed_fields_from_a_realistic_header(tmp_path):
    f = tmp_path / "m.gguf"
    f.write_bytes(_gguf(REALISTIC, tensors=400))

    assert scanner._read_gguf_metadata(f) == {
        "architecture": "qwen3",
        "name": "Qwen3 9B",
        "file_type": "Q5_K_M",
        "context_length": 40960,
    }


def test_stops_reading_once_the_wanted_keys_are_found(tmp_path):
    # Header claims a tokenizer array but the file is cut off right after
    # the keys we need: an early exit parses fine, a full walk would fail.
    complete = _gguf(REALISTIC)
    cut = complete.find(_s("tokenizer.ggml.tokens")) + 20
    f = tmp_path / "m.gguf"
    f.write_bytes(complete[:cut])

    assert scanner._read_gguf_metadata(f)["context_length"] == 40960


def test_finds_keys_that_come_after_a_large_array(tmp_path):
    pairs = [
        ("tokenizer.ggml.tokens", [f"tok{i}" for i in range(20000)]),
        ("tokenizer.ggml.scores", [0] * 20000),
        ("general.name", "Late Name"),
        ("general.architecture", "llama"),
        ("llama.context_length", 8192),
        ("general.file_type", 15),
    ]
    f = tmp_path / "m.gguf"
    f.write_bytes(_gguf(pairs))

    meta = scanner._read_gguf_metadata(f)
    assert meta["name"] == "Late Name"
    assert meta["context_length"] == 8192
    assert meta["file_type"] == "Q4_K_M"


def test_context_length_is_looked_up_under_the_architecture_prefix(tmp_path):
    pairs = [
        ("llama.context_length", 4096),  # wrong arch: must be ignored
        ("general.architecture", "gemma3"),
        ("gemma3.context_length", 131072),
    ]
    f = tmp_path / "m.gguf"
    f.write_bytes(_gguf(pairs))

    meta = scanner._read_gguf_metadata(f)
    assert meta["architecture"] == "gemma3"
    assert meta["context_length"] == 131072
    assert meta["name"] is None
    assert meta["file_type"] is None


def test_unknown_file_type_falls_back_to_the_raw_number(tmp_path):
    f = tmp_path / "m.gguf"
    f.write_bytes(_gguf([("general.file_type", 999)]))

    assert scanner._read_gguf_metadata(f)["file_type"] == "999"


def test_gguf_v2_is_accepted(tmp_path):
    f = tmp_path / "m.gguf"
    f.write_bytes(_gguf([("general.architecture", "llama")], version=2))

    assert scanner._read_gguf_metadata(f)["architecture"] == "llama"


def test_unreadable_files_degrade_to_empty_metadata(tmp_path):
    cases = {
        "empty.gguf": b"",
        "not-gguf.gguf": _gguf([("general.architecture", "llama")], magic=b"GGML"),
        "future-version.gguf": _gguf([("general.architecture", "llama")], version=4),
        "truncated.gguf": _gguf([("general.name", "x" * 100)])[:-40],
        "bad-type.gguf": _gguf([]) [:-8] + struct.pack("<Q", 1) + _s("general.name") + struct.pack("<I", 42),
    }
    for filename, payload in cases.items():
        f = tmp_path / filename
        f.write_bytes(payload)
        assert scanner._read_gguf_metadata(f) == {}, filename


def test_scan_uses_the_parsed_header(tmp_path):
    (tmp_path / "some-file.gguf").write_bytes(_gguf(REALISTIC))

    models = scanner.scan(tmp_path)

    assert models[0].id == "some-file"
    assert models[0].display_name == "Qwen3 9B"
    assert models[0].architecture == "qwen3"
    assert models[0].file_type == "Q5_K_M"
    assert models[0].context_length == 40960


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
