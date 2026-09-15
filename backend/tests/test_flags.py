import pytest

from app import flags
from app.flags import FLAG_SCHEMA, build_args, normalize_flags


def test_build_args_always_starts_with_model_path():
    args = build_args("/models/foo.gguf", {})
    assert args[:2] == ["--model", "/models/foo.gguf"]


def test_build_args_boolean_flag_emits_bare_flag_when_true():
    args = build_args("/m.gguf", {"no_kv_offload": True})
    assert "--no-kv-offload" in args


def test_build_args_boolean_flag_omitted_when_false():
    args = build_args("/m.gguf", {"no_kv_offload": False})
    assert "--no-kv-offload" not in args


def test_build_args_value_flag_emits_flag_followed_by_value():
    args = build_args("/m.gguf", {"ctx_size": 8192})
    i = args.index("--ctx-size")
    assert args[i + 1] == "8192"


def test_build_args_skips_none_and_empty_values():
    args = build_args("/m.gguf", {"seed": None, "api_key": ""})
    assert "--seed" not in args
    assert "--api-key" not in args


def test_build_args_ignores_unknown_keys():
    args = build_args("/m.gguf", {"totally_unknown_flag": "x"})
    assert "totally_unknown_flag" not in args
    assert "x" not in args


def test_flash_attn_is_declared_as_enum_not_boolean():
    # Regression: --flash-attn used to be a bare boolean flag, which made
    # llama-server swallow the next CLI token (e.g. --host) as its own value
    # ("unknown value for --flash-attn: '--host'"). It must always be
    # emitted with an explicit on/off/auto value.
    schema_by_key = {f.key: f for f in FLAG_SCHEMA}
    assert schema_by_key["flash_attn"].type == "enum"

    args = build_args("/m.gguf", {"flash_attn": "auto", "host": "127.0.0.1"})
    i = args.index("--flash-attn")
    assert args[i + 1] == "auto"
    assert args[i + 2] == "--host"


def test_all_flag_keys_and_cli_names_are_unique():
    keys = [f.key for f in FLAG_SCHEMA]
    clis = [f.cli for f in FLAG_SCHEMA]
    assert len(keys) == len(set(keys))
    assert len(clis) == len(set(clis))


def test_enum_flags_always_declare_options():
    for f in FLAG_SCHEMA:
        if f.type == "enum":
            assert f.options, f"{f.key} is declared as enum but has no options"


# --- normalize_flags() ------------------------------------------------------

def test_normalize_keeps_well_typed_values_as_is():
    values = {"ctx_size": 4096, "no_kv_offload": True, "flash_attn": "auto", "host": "0.0.0.0"}
    assert normalize_flags(values) == values


def test_normalize_coerces_numbers_and_booleans_saved_as_strings():
    out = normalize_flags({"ctx_size": "8192", "seed": "-1", "no_kv_offload": "false", "threads": "1.5"})
    assert out == {"ctx_size": 8192, "seed": -1, "no_kv_offload": False, "threads": 1.5}


def test_normalize_coerces_scalars_to_string_for_string_flags():
    assert normalize_flags({"tensor_split": 3, "api_key": True}) == {"tensor_split": "3", "api_key": "true"}


def test_normalize_leaves_unset_values_alone():
    assert normalize_flags({"seed": None, "api_key": ""}) == {"seed": None, "api_key": ""}


def test_normalize_leaves_unconvertible_values_alone():
    assert normalize_flags({"ctx_size": "lots"}) == {"ctx_size": "lots"}


def test_normalize_keeps_unknown_keys():
    # A preset saved by a newer LlamaPanel must not lose flags on an older one.
    assert normalize_flags({"from_the_future": [1, 2]}) == {"from_the_future": [1, 2]}


def test_normalize_applies_renames_including_chains(monkeypatch):
    monkeypatch.setattr(flags, "FLAG_RENAMES", {"old_ctx": "older_ctx", "older_ctx": "ctx_size"})
    assert normalize_flags({"old_ctx": "2048"}) == {"ctx_size": 2048}


def test_normalize_survives_a_rename_cycle(monkeypatch):
    monkeypatch.setattr(flags, "FLAG_RENAMES", {"a": "b", "b": "a"})
    assert normalize_flags({"a": 1}) == {"b": 1}


@pytest.mark.parametrize("old", list(flags.FLAG_RENAMES))
def test_every_rename_points_at_a_key_that_exists_in_the_schema(old):
    target = flags.FLAG_RENAMES[old]
    while target in flags.FLAG_RENAMES:
        target = flags.FLAG_RENAMES[target]
    assert target in {f.key for f in FLAG_SCHEMA}
