from app.flags import FLAG_SCHEMA, build_args


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
