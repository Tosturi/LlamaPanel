"""Parser tests run against tests/fixtures/llama_server_help.txt, a verbatim
`llama-server --help` capture. Update the fixture from a newer build when
llama.cpp changes the format and see what breaks."""

import subprocess
from pathlib import Path

import pytest

from app import introspection
from app.introspection import (
    BinaryInspector,
    HelpParseError,
    parse_help,
    parse_help_to_args,
    parse_version,
    resolve_binary,
)

FIXTURE = Path(__file__).parent / "fixtures" / "llama_server_help.txt"


@pytest.fixture(scope="module")
def help_text() -> str:
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def raw_by_first_arg(help_text):
    # First occurrence wins, like parse_help_to_args.
    out = {}
    for e in parse_help(help_text):
        out.setdefault(e.args[0], e)
    return out


@pytest.fixture(scope="module")
def args_by_key(help_text):
    return {a.key: a for a in parse_help_to_args(help_text)}


# --- raw parsing -------------------------------------------------------------

def test_parse_help_finds_every_option(help_text):
    # Entry lines start at column 0 with a dash; that is the whole count.
    expected = sum(1 for line in help_text.splitlines() if line.startswith("-") and not line.startswith("-----"))
    assert len(parse_help(help_text)) == expected
    assert expected > 200


def test_parse_help_tracks_sections(raw_by_first_arg):
    assert raw_by_first_arg["-c"].section == "common params"
    assert raw_by_first_arg["--temp"].section == "sampling params"
    assert raw_by_first_arg["--spec-draft-n-max"].section == "speculative params"
    assert raw_by_first_arg["--host"].section == "example-specific params"


def test_parse_help_reads_help_from_the_same_line_and_continuations(raw_by_first_arg):
    threads = raw_by_first_arg["-t"]
    assert threads.help_lines == [
        "number of CPU threads to use during generation (default: -1)",
        "(env: LLAMA_ARG_THREADS)",
    ]


def test_parse_help_handles_head_too_long_for_one_line(raw_by_first_arg):
    kv = raw_by_first_arg["-kvo"]
    assert kv.args == ["-kvo", "--kv-offload", "-nkvo", "--no-kv-offload"]
    assert kv.hints == []
    assert kv.help_lines[0].startswith("whether to enable KV cache offloading")


def test_parse_help_survives_indented_blank_lines_inside_an_entry(raw_by_first_arg):
    # --load-mode has an empty (but indented) line before its (env: ...) line.
    assert raw_by_first_arg["-lm"].help_lines[-1] == "(env: LLAMA_ARG_LOAD_MODE)"


def test_parse_help_separates_spellings_from_value_hints(raw_by_first_arg):
    assert raw_by_first_arg["-ngl"].args == ["-ngl", "--gpu-layers", "--n-gpu-layers"]
    assert raw_by_first_arg["-ngl"].hints == ["N"]
    assert raw_by_first_arg["--control-vector-layer-range"].hints == ["START", "END"]
    assert raw_by_first_arg["--override-kv"].hints == ["KEY=TYPE:VALUE,..."]
    assert raw_by_first_arg["-ts"].hints == ["N0,N1,N2,..."]
    # Padding after a long first spelling is still just a separator.
    assert raw_by_first_arg["--ui"].args == ["--ui", "--webui", "--no-ui", "--no-webui"]


def test_parse_help_rejects_garbage():
    with pytest.raises(HelpParseError):
        parse_help("llama-server: command not found\n")


# --- keys and spellings ------------------------------------------------------

def test_key_is_derived_from_the_first_long_spelling(args_by_key):
    assert args_by_key["ctx_size"].args == ["-c", "--ctx-size"]
    assert args_by_key["gpu_layers"].args == ["-ngl", "--gpu-layers", "--n-gpu-layers"]
    assert "n_gpu_layers" not in args_by_key  # alias, not a separate key


def test_duplicate_entries_keep_the_first_occurrence(help_text):
    # Some builds list an option in two sections; the snapshot doesn't, so
    # append a second --mmproj entry and check it is folded away.
    text = help_text + "\n\n----- extra params -----\n\n-mm,   --mmproj FILE                    duplicated entry\n"
    args = [a for a in parse_help_to_args(text) if a.key == "mmproj"]
    assert len(args) == 1
    assert args[0].section == "example-specific params"


def test_every_arg_has_a_unique_key_and_non_empty_spellings(help_text):
    args = parse_help_to_args(help_text)
    keys = [a.key for a in args]
    assert len(keys) == len(set(keys))
    assert all(a.args for a in args)


# --- booleans ----------------------------------------------------------------

def test_bare_switch_is_boolean_with_false_default(args_by_key):
    for key in ("swa_full", "metrics", "list_devices", "no_host"):
        arg = args_by_key[key]
        assert arg.type == "boolean", key
        assert arg.default is False, key
        assert arg.args_neg == [], key


def test_positive_negative_pair_is_one_boolean_with_default_from_text(args_by_key):
    kv = args_by_key["kv_offload"]
    assert kv.type == "boolean"
    assert kv.args == ["-kvo", "--kv-offload"]
    assert kv.args_neg == ["-nkvo", "--no-kv-offload"]
    assert kv.default is True
    assert "no_kv_offload" not in args_by_key

    assert args_by_key["repack"].args_neg == ["-nr", "--no-repack"]
    assert args_by_key["agent"].args_neg == ["-no-ag", "--no-agent"]
    assert args_by_key["context_shift"].default is False
    assert args_by_key["escape"].default is True


def test_pair_default_split_across_wrapped_lines(args_by_key):
    # "(default:\n false)"
    assert args_by_key["perf"].default is False


def test_pair_with_extra_negative_aliases(args_by_key):
    ui = args_by_key["ui"]
    assert ui.args == ["--ui", "--webui"]
    assert ui.args_neg == ["--no-ui", "--no-webui"]
    mmproj_auto = args_by_key["mmproj_auto"]
    assert mmproj_auto.args_neg == ["--no-mmproj", "--no-mmproj-auto"]


def test_pair_defaults_with_prose(args_by_key):
    assert args_by_key["cache_idle_slots"].default is True  # "enabled, requires cache-ram"
    assert args_by_key["prefill_assistant"].default is True  # "prefill enabled"
    assert args_by_key["kv_unified"].default is None  # "enabled if number of slots is auto"


# --- numbers -----------------------------------------------------------------

def test_numeric_hint_yields_number_with_parsed_default(args_by_key):
    assert (args_by_key["ctx_size"].type, args_by_key["ctx_size"].default) == ("number", 0)
    assert args_by_key["threads"].default == -1
    assert args_by_key["batch_size"].default == 2048
    assert args_by_key["temp"].default == 0.8
    assert args_by_key["top_k"].default == 40
    assert args_by_key["mirostat"].default == 0
    assert args_by_key["video_fps"].default == 4.0


def test_numeric_default_split_across_wrapped_lines(args_by_key):
    assert args_by_key["keep"].default == 0  # "(default: 0, -1 =\n all)"
    assert args_by_key["cache_ram"].default == 8192


def test_numeric_hint_with_prose_default_has_no_default(args_by_key):
    assert args_by_key["threads_batch"].type == "number"
    assert args_by_key["threads_batch"].default is None  # "same as --threads"
    assert args_by_key["rope_freq_base"].default is None  # "loaded from model"


def test_uppercase_hint_with_numeric_default_is_a_number(args_by_key):
    assert (args_by_key["port"].type, args_by_key["port"].default) == ("number", 8080)
    assert (args_by_key["seed"].type, args_by_key["seed"].default) == ("number", -1)
    assert (args_by_key["main_gpu"].type, args_by_key["main_gpu"].default) == ("number", 0)
    assert (args_by_key["sleep_idle_seconds"].type, args_by_key["sleep_idle_seconds"].default) == ("number", -1)


def test_range_hint_is_a_number(args_by_key):
    assert (args_by_key["poll"].type, args_by_key["poll"].default) == ("number", 50)


def test_numeric_hint_with_word_default_becomes_string(args_by_key):
    # -ngl N accepts an integer, 'auto' or 'all' and defaults to auto.
    ngl = args_by_key["gpu_layers"]
    assert ngl.type == "string"
    assert ngl.default == "auto"


# --- strings and paths -------------------------------------------------------

def test_uppercase_hint_with_text_default_stays_a_string(args_by_key):
    assert (args_by_key["host"].type, args_by_key["host"].default) == ("string", "127.0.0.1")
    assert args_by_key["cors_methods"].default == "GET, POST, DELETE, OPTIONS"
    assert args_by_key["cors_origins"].default == "*"


def test_text_default_without_spaces_is_kept_verbatim(args_by_key):
    # Wrapped: "(default:\n penalties;dry;...)"
    assert args_by_key["samplers"].default == "penalties;dry;top_n_sigma;top_k;typ_p;top_p;min_p;xtc;temperature"


def test_prose_defaults_mean_unset(args_by_key):
    assert args_by_key["api_key"].default is None  # none
    assert args_by_key["slot_save_path"].default is None  # disabled
    assert args_by_key["model_url"].default is None  # unused
    assert args_by_key["path"].default is None  # "(default: )"
    assert args_by_key["cpu_mask"].default is None  # '(default: "")'
    assert args_by_key["hf_token"].default is None  # "value from HF_TOKEN environment variable"
    assert args_by_key["chat_template"].default is None
    assert args_by_key["kv_unified_per_slot"].default is None  # "unset, behavior unchanged"
    assert args_by_key["kv_unified_per_slot"].type == "number"


def test_path_like_hints_yield_path(args_by_key):
    for key in ("model", "mmproj", "api_key_file", "slot_save_path", "video_ffmpeg_dir", "chat_template_file"):
        assert args_by_key[key].type == "path", key


def test_structured_hints_fall_back_to_string(args_by_key):
    assert args_by_key["lora_scaled"].type == "string"  # FNAME:SCALE,...
    assert args_by_key["override_kv"].type == "string"
    assert args_by_key["tensor_split"].type == "string"
    assert args_by_key["override_tensor"].type == "string"
    assert args_by_key["control_vector_layer_range"].type == "string"
    assert args_by_key["control_vector_layer_range"].value_hints == ["START", "END"]
    assert args_by_key["docker_repo"].type == "string"  # [<repo>/]<model>[:quant] is not an enum


# --- enums -------------------------------------------------------------------

def test_bracket_hint_yields_enum(args_by_key):
    fa = args_by_key["flash_attn"]
    assert (fa.type, fa.options, fa.default) == ("enum", ["on", "off", "auto"], "auto")
    assert (args_by_key["fit"].options, args_by_key["fit"].default) == (["on", "off"], "on")


def test_bracket_default_followed_by_a_parenthetical(args_by_key):
    # "(default:\n 'auto' (detect from template))"
    assert args_by_key["reasoning"].default == "auto"


def test_angle_hint_yields_enum(args_by_key):
    assert (args_by_key["cpu_strict"].options, args_by_key["cpu_strict"].default) == (["0", "1"], "0")
    assert args_by_key["cpu_strict_batch"].default is None  # "same as --cpu-strict"


def test_brace_hint_yields_enum(args_by_key):
    assert args_by_key["rope_scaling"].options == ["none", "linear", "yarn"]
    assert args_by_key["rope_scaling"].default is None
    assert args_by_key["split_mode"].options == ["none", "layer", "row", "tensor"]
    assert args_by_key["pooling"].options == ["none", "mean", "cls", "last", "rank"]


def test_bare_comma_list_hint_yields_enum(args_by_key):
    spec = args_by_key["spec_type"]
    assert spec.type == "enum"
    assert spec.options[:3] == ["none", "draft-simple", "draft-eagle3"]
    assert spec.options[-1] == "ngram-cache"
    assert spec.default == "none"  # a real option here, not "unset"


def test_allowed_values_list_in_help_yields_enum(args_by_key):
    ctk = args_by_key["cache_type_k"]
    assert ctk.type == "enum"
    assert ctk.options == ["f32", "f16", "bf16", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1"]
    assert ctk.default == "f16"


def test_bullet_list_under_a_mode_hint_yields_enum(args_by_key):
    lm = args_by_key["load_mode"]
    assert lm.type == "enum"
    assert lm.options == ["auto", "none", "mmap", "mlock", "mmap+mlock", "dio"]
    assert lm.default == "auto"
    assert args_by_key["lazy_mode"].options == ["on", "auto", "off"]
    assert args_by_key["numa"].options == ["distribute", "isolate", "numactl"]
    assert args_by_key["reasoning_format"].options == ["none", "deepseek", "deepseek-legacy"]


def test_numbered_bullets_under_an_n_hint_do_not_become_an_enum(args_by_key):
    assert (args_by_key["verbosity"].type, args_by_key["verbosity"].default) == ("number", 3)
    assert args_by_key["verbosity"].options is None


# --- misc metadata -----------------------------------------------------------

def test_repeatable_is_detected_from_help_text(args_by_key):
    assert args_by_key["lora"].repeatable is True
    assert args_by_key["override_kv"].repeatable is True
    assert args_by_key["ctx_size"].repeatable is False


def test_deprecated_is_detected_from_help_text(args_by_key):
    assert args_by_key["defrag_thold"].deprecated is True
    assert args_by_key["draft"].deprecated is True  # "the argument has been removed"
    assert args_by_key["ctx_size"].deprecated is False


def test_env_var_is_extracted_and_removed_from_help(args_by_key):
    threads = args_by_key["threads"]
    assert threads.env == "LLAMA_ARG_THREADS"
    assert "env:" not in threads.help
    assert args_by_key["load_mode"].env == "LLAMA_ARG_LOAD_MODE"  # after an indented blank line
    assert args_by_key["hf_token"].env == "HF_TOKEN"
    assert args_by_key["swa_full"].env == "LLAMA_ARG_SWA_FULL"
    assert args_by_key["keep"].env is None


def test_help_is_reflowed_for_display(args_by_key):
    # Soft wraps are joined; bullets and parenthetical notes keep their lines.
    assert args_by_key["threads_batch"].help == (
        "number of threads to use during batch and prompt processing (default: same as --threads)"
    )
    lines = args_by_key["load_mode"].help.split("\n")
    assert lines[0] == "model loading mode (default: auto)"
    assert lines[1] == "- auto: mmap, unless a device does not support it"
    assert lines[3] == "- mmap: memory-map model (if mmap disabled, slower load but may reduce pageouts if not using mlock)"
    assert "" not in lines


# --- version -----------------------------------------------------------------

def test_parse_version_reads_build_and_commit():
    assert parse_version("version: 6789 (a1b2c3d)\nbuilt with MSVC 19.44 for x64\n") == (6789, "a1b2c3d")


def test_parse_version_handles_unknown_commit_and_garbage():
    assert parse_version("version: 0 (unknown)") == (0, "unknown")
    assert parse_version("something else entirely") == (None, None)


# --- binary resolution and probing ------------------------------------------

def test_resolve_binary_prefers_an_existing_path(tmp_path):
    exe = tmp_path / "llama-server"
    exe.write_bytes(b"")
    assert resolve_binary(str(exe)) == exe.resolve()


def test_resolve_binary_falls_back_to_path_lookup(monkeypatch, tmp_path):
    exe = tmp_path / "llama-server"
    exe.write_bytes(b"")
    monkeypatch.setattr(introspection.shutil, "which", lambda name: str(exe) if name == "llama-server" else None)
    assert resolve_binary("llama-server") == exe.resolve()
    assert resolve_binary("definitely-not-installed") is None


def _fake_run(outputs: dict[str, object]):
    calls: list[str] = []

    def run(binary, *args):
        calls.append(args[0])
        out = outputs[args[0]]
        if isinstance(out, Exception):
            raise out
        return out

    return run, calls


def test_inspector_reports_missing_binary_without_raising(monkeypatch):
    monkeypatch.setattr(introspection.shutil, "which", lambda name: None)
    info = BinaryInspector("nope-server").inspect()
    assert info.resolved_path is None
    assert info.args == []
    assert "not found" in info.error


def test_inspector_combines_version_and_help(monkeypatch, tmp_path, help_text):
    exe = tmp_path / "llama-server"
    exe.write_bytes(b"x")
    run, _ = _fake_run({"--version": "version: 42 (deadbee)\n", "--help": help_text})
    monkeypatch.setattr(introspection, "_run", run)

    info = BinaryInspector(str(exe)).inspect()

    assert info.resolved_path == str(exe.resolve())
    assert (info.build, info.commit) == (42, "deadbee")
    assert {a.key for a in info.args} >= {"ctx_size", "flash_attn", "host"}
    assert info.error is None


def test_inspector_caches_until_the_binary_changes(monkeypatch, tmp_path, help_text):
    exe = tmp_path / "llama-server"
    exe.write_bytes(b"x")
    run, calls = _fake_run({"--version": "version: 1 (a)\n", "--help": help_text})
    monkeypatch.setattr(introspection, "_run", run)
    inspector = BinaryInspector(str(exe))

    inspector.inspect()
    inspector.inspect()
    assert calls == ["--version", "--help"]

    inspector.inspect(force=True)
    assert len(calls) == 4

    exe.write_bytes(b"a different build")  # size changes -> new fingerprint
    inspector.inspect()
    assert len(calls) == 6


def test_inspector_reports_a_broken_help_but_keeps_the_version(monkeypatch, tmp_path):
    exe = tmp_path / "llama-server"
    exe.write_bytes(b"x")
    run, _ = _fake_run({"--version": "version: 7 (abc)\n", "--help": "error: unknown argument: --help\n"})
    monkeypatch.setattr(introspection, "_run", run)

    info = BinaryInspector(str(exe)).inspect()

    assert info.build == 7
    assert info.args == []
    assert "--help failed" in info.error


def test_inspector_reports_a_timeout(monkeypatch, tmp_path):
    exe = tmp_path / "llama-server"
    exe.write_bytes(b"x")
    run, _ = _fake_run({
        "--version": subprocess.TimeoutExpired(cmd="llama-server", timeout=1),
        "--help": subprocess.TimeoutExpired(cmd="llama-server", timeout=1),
    })
    monkeypatch.setattr(introspection, "_run", run)

    info = BinaryInspector(str(exe)).inspect()

    assert info.build is None
    assert info.args == []
    assert "--version failed" in info.error and "--help failed" in info.error


# --- endpoint ----------------------------------------------------------------

def test_binary_endpoint_returns_info_even_when_binary_is_missing(client, monkeypatch):
    monkeypatch.setattr(introspection.shutil, "which", lambda name: None)
    resp = client.get("/api/server/binary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["server_bin"] == "llama-server"
    assert body["resolved_path"] is None
    assert body["args"] == []
    assert "not found" in body["error"]


def test_binary_endpoint_serves_parsed_args(client, monkeypatch, tmp_path, help_text):
    exe = tmp_path / "llama-server"
    exe.write_bytes(b"x")
    monkeypatch.setattr(introspection, "resolve_binary", lambda server_bin: exe.resolve())
    run, calls = _fake_run({"--version": "version: 9 (cafe)\n", "--help": help_text})
    monkeypatch.setattr(introspection, "_run", run)

    body = client.get("/api/server/binary").json()
    assert body["build"] == 9
    keys = {a["key"] for a in body["args"]}
    assert {"ctx_size", "kv_offload", "flash_attn"} <= keys

    client.get("/api/server/binary")
    assert len(calls) == 2  # cached
    client.get("/api/server/binary?refresh=true")
    assert len(calls) == 4
