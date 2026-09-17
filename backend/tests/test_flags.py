"""Schema building, preset-key resolution and argv round-trips, all against
the bundled --help snapshot (app/snapshots/llama-server-help.txt)."""

import pytest

from app import flags
from app.flags import (
    CURATED,
    HIDDEN,
    FlagCatalog,
    build_args,
    build_schema,
    bundled_schema,
    normalize_flags,
    parse_args,
    resolve_flags,
)
from app.introspection import parse_help_to_args
from app.schemas import BinaryInfo, FlagDef


@pytest.fixture(scope="module")
def schema() -> list[FlagDef]:
    return bundled_schema()


@pytest.fixture(scope="module")
def by_key(schema):
    return {f.key: f for f in schema}


# --- build_schema ------------------------------------------------------------

def test_schema_covers_the_whole_help_minus_hidden_and_deprecated(schema):
    keys = {f.key for f in schema}
    assert len(schema) > 200
    assert {"ctx_size", "threads", "temp", "spec_draft_n_max", "host", "cache_type_k"} <= keys
    assert not {"help", "version", "model", "hf_repo", "log_file", "models_dir", "spec_default"} & keys
    assert not {"defrag_thold", "draft", "draft_min"} & keys  # deprecated


def test_every_key_cli_and_spelling_is_unique(schema):
    keys = [f.key for f in schema]
    clis = [f.cli for f in schema]
    spellings = [a for f in schema for a in f.aliases + f.aliases_neg]
    assert len(keys) == len(set(keys))
    assert len(clis) == len(set(clis))
    assert len(spellings) == len(set(spellings))


def test_curated_flags_come_first_in_curated_order_and_are_labelled(schema):
    curated_keys = [f.key for f in schema if f.group == "basic" or f.label != f.cli]
    assert schema[: len(curated_keys)] == [f for f in schema if f.key in curated_keys]
    basic = [f.key for f in schema if f.group == "basic"]
    assert basic == ["n_gpu_layers", "ctx_size", "kv_offload", "flash_attn", "host", "port", "seed"]
    labels = {f.key: f.label for f in schema}
    assert labels["ctx_size"] == "Context Size"
    assert labels["load_mode"] == "Model Load Mode"


def test_uncurated_flags_are_labelled_by_their_cli_and_grouped_by_section(schema, by_key):
    assert by_key["ubatch_size"].label == "--ubatch-size"
    assert by_key["ubatch_size"].group == "advanced"
    rest = [f for f in schema if f.group == "advanced" and f.label == f.cli]
    sections = [f.section for f in rest]
    # common, then server-specific, then sampling, then speculative - never interleaved.
    order = [flags.SECTION_ORDER.index(s) for s in sections]
    assert order == sorted(order)


def test_curated_key_is_pinned_even_when_the_binary_lists_another_spelling_first(by_key):
    ngl = by_key["n_gpu_layers"]
    assert ngl.cli == "--gpu-layers"  # what this build prints first
    assert ngl.aliases == ["-ngl", "--gpu-layers", "--n-gpu-layers"]
    assert "gpu_layers" not in by_key


def test_boolean_pair_carries_both_spellings(by_key):
    kv = by_key["kv_offload"]
    assert (kv.cli, kv.cli_neg) == ("--kv-offload", "--no-kv-offload")
    assert kv.aliases_neg == ["-nkvo", "--no-kv-offload"]
    assert kv.default is True
    assert by_key["swa_full"].cli_neg is None


def test_help_env_and_section_are_carried_over(by_key):
    assert by_key["ctx_size"].env == "LLAMA_ARG_CTX_SIZE"
    assert by_key["ctx_size"].section == "common params"
    assert by_key["ctx_size"].help.startswith("size of the prompt context")
    assert by_key["lora"].repeatable is True


def test_every_curated_and_hidden_spelling_exists_in_the_snapshot():
    """Catches typos in the overlay: a spelling nobody prints never matches."""
    spellings = {a for arg in parse_help_to_args(flags.SNAPSHOT_PATH.read_text(encoding="utf-8")) for a in arg.args + arg.args_neg}
    for c in CURATED:
        assert set(c.match) & spellings, c
    for h in HIDDEN:
        assert h in spellings, h


def test_enum_flags_always_declare_options(schema):
    for f in schema:
        if f.type == "enum":
            assert f.options, f"{f.key} is declared as enum but has no options"


# --- resolve_flags -----------------------------------------------------------

def test_resolve_keeps_well_typed_values_as_is(schema):
    values = {"ctx_size": 4096, "kv_offload": True, "flash_attn": "auto", "host": "0.0.0.0"}
    assert resolve_flags(values, schema) == (values, [])


def test_resolve_coerces_numbers_and_booleans_saved_as_strings(schema):
    out = normalize_flags({"ctx_size": "8192", "seed": "-1", "kv_offload": "false", "threads": "1.5"}, schema)
    assert out == {"ctx_size": 8192, "seed": -1, "kv_offload": False, "threads": 1.5}


def test_resolve_coerces_scalars_to_string_for_string_flags(schema):
    assert normalize_flags({"tensor_split": 3, "api_key": True}, schema) == {"tensor_split": "3", "api_key": "true"}


def test_resolve_leaves_unset_and_unconvertible_values_alone(schema):
    assert normalize_flags({"seed": None, "api_key": "", "ctx_size": "lots"}, schema) == {
        "seed": None, "api_key": "", "ctx_size": "lots",
    }


def test_resolve_matches_a_key_by_any_long_spelling(schema):
    # Saved as gpu_layers by a build that printed --gpu-layers first; the
    # curated key here is n_gpu_layers.
    assert normalize_flags({"gpu_layers": "999"}, schema) == {"n_gpu_layers": "999"}
    # --predict / --n-predict are aliases; first long spelling is the key.
    assert normalize_flags({"n_predict": 128}, schema) == {"predict": 128}


def test_resolve_inverts_a_negative_spelling_of_a_boolean_pair(schema):
    # Presets from before the pair existed stored no_kv_offload: true.
    assert normalize_flags({"no_kv_offload": True}, schema) == {"kv_offload": False}
    assert normalize_flags({"no_kv_offload": "false"}, schema) == {"kv_offload": True}
    assert normalize_flags({"no_webui": True}, schema) == {"ui": False}


def test_resolve_reports_unknown_keys_and_keeps_them(schema):
    out, unsupported = resolve_flags({"from_the_future": [1, 2], "ctx_size": 1}, schema)
    assert out == {"from_the_future": [1, 2], "ctx_size": 1}
    assert unsupported == ["from_the_future"]


def test_resolve_reports_deprecated_flags_as_unsupported(schema):
    # --draft-max is still printed by this build but "has been removed".
    _, unsupported = resolve_flags({"draft_max": 16}, schema)
    assert unsupported == ["draft_max"]


def test_resolve_applies_renames_including_chains(schema, monkeypatch):
    monkeypatch.setattr(flags, "FLAG_RENAMES", {"old_ctx": "older_ctx", "older_ctx": "ctx_size"})
    assert normalize_flags({"old_ctx": "2048"}, schema) == {"ctx_size": 2048}


def test_resolve_survives_a_rename_cycle(schema, monkeypatch):
    monkeypatch.setattr(flags, "FLAG_RENAMES", {"a": "b", "b": "a"})
    assert resolve_flags({"a": 1}, schema) == ({"a": 1}, ["a"])


@pytest.mark.parametrize("old", list(flags.FLAG_RENAMES))
def test_every_rename_points_at_a_key_that_exists_in_the_schema(old, by_key):
    target = flags.FLAG_RENAMES[old]
    while target in flags.FLAG_RENAMES:
        target = flags.FLAG_RENAMES[target]
    assert target in by_key


def test_resolve_accepts_a_list_for_a_repeatable_flag(schema):
    assert normalize_flags({"lora": ["/a.gguf", "/b.gguf"]}, schema) == {"lora": ["/a.gguf", "/b.gguf"]}


# --- build_args --------------------------------------------------------------

def test_build_args_always_starts_with_model_path(schema):
    assert build_args("/models/foo.gguf", {}, schema)[:2] == ["--model", "/models/foo.gguf"]


def test_build_args_value_flag_emits_flag_followed_by_value(schema):
    args = build_args("/m.gguf", {"ctx_size": 8192}, schema)
    assert args[args.index("--ctx-size") + 1] == "8192"


def test_build_args_skips_none_and_empty_values(schema):
    args = build_args("/m.gguf", {"seed": None, "api_key": "", "lora": []}, schema)
    assert args == ["--model", "/m.gguf"]


def test_build_args_skips_values_equal_to_the_documented_default(schema):
    args = build_args("/m.gguf", {"port": 8080, "host": "127.0.0.1", "flash_attn": "auto", "temp": 0.8}, schema)
    assert args == ["--model", "/m.gguf"]
    args = build_args("/m.gguf", {"port": 8081}, schema)
    assert args[2:] == ["--port", "8081"]


def test_build_args_ignores_unknown_keys(schema):
    args = build_args("/m.gguf", {"totally_unknown_flag": "x"}, schema)
    assert args == ["--model", "/m.gguf"]


def test_build_args_plain_switch_is_emitted_only_when_true(schema):
    assert "--swa-full" in build_args("/m.gguf", {"swa_full": True}, schema)
    assert "--swa-full" not in build_args("/m.gguf", {"swa_full": False}, schema)


def test_build_args_boolean_pair_emits_the_negative_spelling_to_turn_a_default_off(schema):
    # kv-offload is enabled by default: True is a no-op, False needs --no-kv-offload.
    assert build_args("/m.gguf", {"kv_offload": True}, schema) == ["--model", "/m.gguf"]
    assert build_args("/m.gguf", {"kv_offload": False}, schema)[2:] == ["--no-kv-offload"]
    # context-shift is disabled by default: the positive spelling turns it on.
    assert build_args("/m.gguf", {"context_shift": True}, schema)[2:] == ["--context-shift"]
    assert build_args("/m.gguf", {"context_shift": False}, schema) == ["--model", "/m.gguf"]


def test_build_args_boolean_pair_with_unknown_default_is_always_explicit(schema):
    # kv-unified's default is conditional ("enabled if number of slots is auto").
    assert build_args("/m.gguf", {"kv_unified": True}, schema)[2:] == ["--kv-unified"]
    assert build_args("/m.gguf", {"kv_unified": False}, schema)[2:] == ["--no-kv-unified"]


def test_build_args_emits_a_repeatable_flag_once_per_item(schema):
    args = build_args("/m.gguf", {"lora": ["/a.gguf", "/b.gguf"]}, schema)
    assert args[2:] == ["--lora", "/a.gguf", "--lora", "/b.gguf"]


def test_build_args_uses_the_canonical_spelling_for_pinned_keys(schema):
    args = build_args("/m.gguf", {"n_gpu_layers": 999}, schema)
    assert args[2:] == ["--gpu-layers", "999"]


def test_flash_attn_is_an_enum_and_is_emitted_with_a_value(by_key, schema):
    # Regression: as a bare boolean, --flash-attn swallowed the next token.
    assert by_key["flash_attn"].type == "enum"
    args = build_args("/m.gguf", {"flash_attn": "on", "host": "0.0.0.0"}, schema)
    i = args.index("--flash-attn")
    assert args[i + 1 : i + 3] == ["on", "--host"]


# --- parse_args (adoption) ---------------------------------------------------

def test_parse_args_round_trips_build_args(schema):
    values = {"ctx_size": 8192, "kv_offload": False, "flash_attn": "on", "n_gpu_layers": "40", "lora": ["/a", "/b"]}
    model_path, parsed = parse_args(["llama-server", *build_args("/m.gguf", values, schema)], schema)
    assert model_path == "/m.gguf"
    assert parsed == values


def test_parse_args_understands_short_and_negative_spellings(schema):
    argv = ["llama-server", "-m", "/m.gguf", "-c", "4096", "-nkvo", "-ngl", "12", "--no-webui", "--temp", "0.5"]
    model_path, parsed = parse_args(argv, schema)
    assert model_path == "/m.gguf"
    assert parsed == {"ctx_size": 4096, "kv_offload": False, "n_gpu_layers": "12", "ui": False, "temp": 0.5}


def test_parse_args_skips_unknown_tokens_and_dangling_flags(schema):
    _, parsed = parse_args(["llama-server", "--mystery", "7", "--ctx-size"], schema)
    assert parsed == {}


# --- FlagCatalog -------------------------------------------------------------

class _FakeInspector:
    def __init__(self, info: BinaryInfo) -> None:
        self.info = info
        self.calls = 0

    def inspect(self, force: bool = False) -> BinaryInfo:
        self.calls += 1
        return self.info


def test_catalog_builds_from_the_binary_when_it_was_probed():
    args = parse_help_to_args(flags.SNAPSHOT_PATH.read_text(encoding="utf-8"))[:40]
    catalog = FlagCatalog(_FakeInspector(BinaryInfo(server_bin="x", args=args)))
    schema = catalog.schema()
    assert catalog.source == "binary"
    assert {f.key for f in schema} <= {flags.key_from_cli([a for a in x.args if a.startswith("--")][0]) for x in args} | {"n_gpu_layers", "kv_offload"}
    assert catalog.schema() is schema  # same BinaryInfo -> cached


def test_catalog_falls_back_to_the_bundled_snapshot():
    catalog = FlagCatalog(_FakeInspector(BinaryInfo(server_bin="x", error="not found")))
    assert len(catalog.schema()) == len(bundled_schema())
    assert catalog.source == "bundled"


def test_catalog_rebuilds_when_the_inspector_reports_a_new_binary():
    inspector = _FakeInspector(BinaryInfo(server_bin="x", error="not found"))
    catalog = FlagCatalog(inspector)
    first = catalog.schema()
    inspector.info = BinaryInfo(server_bin="x", args=parse_help_to_args(flags.SNAPSHOT_PATH.read_text(encoding="utf-8"))[:10])
    second = catalog.schema()
    assert second is not first
    assert catalog.source == "binary"
    assert len(second) < len(first)


def test_build_schema_on_empty_input_is_empty():
    assert build_schema([]) == []
