from app.schemas import FlagDef

# Single source of truth for llama-server flags. The frontend fetches this
# schema and renders the form generically instead of hardcoding fields.
FLAG_SCHEMA: list[FlagDef] = [
    # --- basic ---
    FlagDef(
        key="n_gpu_layers", cli="--n-gpu-layers", type="number",
        label="GPU Layers (-ngl)", group="basic", default=999,
        help="Number of model layers to offload to GPU. Use a large number (e.g. 999) to offload all.",
    ),
    FlagDef(
        key="ctx_size", cli="--ctx-size", type="number",
        label="Context Size", group="basic", default=4096,
    ),
    FlagDef(
        key="no_kv_offload", cli="--no-kv-offload", type="boolean",
        label="Keep KV cache in RAM (--no-kv-offload)", group="basic", default=False,
        help="Keeps the KV cache on CPU/RAM even when model layers are offloaded to GPU.",
    ),
    FlagDef(
        key="flash_attn", cli="--flash-attn", type="enum",
        label="Flash Attention", group="basic", default="auto",
        options=["on", "off", "auto"],
    ),
    FlagDef(
        key="host", cli="--host", type="string",
        label="Host", group="basic", default="127.0.0.1",
    ),
    FlagDef(
        key="port", cli="--port", type="number",
        label="Port", group="basic", default=8080,
    ),
    FlagDef(
        key="seed", cli="--seed", type="number",
        label="Seed", group="basic", default=-1,
        help="RNG seed. -1 = random on each start.",
    ),
    # --- advanced ---
    FlagDef(
        key="cache_type_k", cli="--cache-type-k", type="enum",
        label="KV Cache Type (K)", group="advanced",
        options=["f32", "f16", "bf16", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1"],
    ),
    FlagDef(
        key="cache_type_v", cli="--cache-type-v", type="enum",
        label="KV Cache Type (V)", group="advanced",
        options=["f32", "f16", "bf16", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1"],
    ),
    FlagDef(
        key="split_mode", cli="--split-mode", type="enum",
        label="Split Mode", group="advanced",
        options=["none", "layer", "row", "tensor"],
    ),
    FlagDef(
        key="mmproj", cli="--mmproj", type="path",
        label="Vision Projector (--mmproj)", group="advanced",
        help="Path to a multimodal projector GGUF. Leave empty to run text-only.",
    ),
    FlagDef(
        key="override_tensor", cli="--override-tensor", type="string",
        label="Override Tensor (--override-tensor)", group="advanced",
        help="Regex pattern to force specific tensors onto a device, e.g. 'blk\\.(2[0-9])\\..*=CPU'",
    ),
    FlagDef(
        key="batch_size", cli="--batch-size", type="number",
        label="Batch Size", group="advanced",
    ),
    FlagDef(
        key="threads", cli="--threads", type="number",
        label="CPU Threads", group="advanced",
    ),
    FlagDef(
        key="spec_type", cli="--spec-type", type="enum",
        label="Speculative Decoding Type (--spec-type)", group="advanced",
        options=[
            "none", "draft-simple", "draft-eagle3", "draft-mtp", "draft-dflash",
            "draft-dspark", "ngram-simple", "ngram-map-k", "ngram-map-k4v",
            "ngram-mod", "ngram-cache",
        ],
        help="llama-server also accepts a comma-separated list here for multiple types; pick one from this list to cover the common case.",
    ),
    FlagDef(
        key="spec_draft_n_max", cli="--spec-draft-n-max", type="number",
        label="Max Draft Tokens (--spec-draft-n-max)", group="advanced",
    ),
    FlagDef(
        key="parallel", cli="--parallel", type="number",
        label="Server Slots (--parallel)", group="advanced",
        help="Number of concurrent request slots. -1 = auto.",
    ),
    FlagDef(
        key="tensor_split", cli="--tensor-split", type="string",
        label="Tensor Split (--tensor-split)", group="advanced",
        help="Comma-separated per-GPU split ratios for multi-GPU setups, e.g. '3,1'.",
    ),
    FlagDef(
        key="load_mode", cli="--load-mode", type="enum",
        label="Model Load Mode (--load-mode)", group="advanced",
        options=["auto", "none", "mmap", "mlock", "mmap+mlock", "dio"],
        help="Replaces the old --mlock/--no-mmap flags. 'mlock' pins the model in RAM instead of letting it page out; 'mmap+mlock' keeps mmap's fast load with that same guarantee.",
    ),
    FlagDef(
        key="api_key", cli="--api-key", type="string",
        label="API Key (--api-key)", group="advanced",
        help="Requires this key as a Bearer token on every request to llama-server's own API. Leave empty to leave it open.",
    ),
]


# Old preset key -> current key. When a flag is renamed in FLAG_SCHEMA, add
# the old key here and saved presets keep working without a format bump.
# Chains (a -> b -> c) are followed.
FLAG_RENAMES: dict[str, str] = {}


def _coerce_value(flag: FlagDef, value):
    """Best-effort conversion of a stored value to the type FLAG_SCHEMA now
    declares (a flag that changed from string to number, a boolean saved
    as "true", ...). Unknown or unconvertible values are returned as-is;
    None/"" mean "unset" and stay that way."""
    if value is None or value == "":
        return value
    if flag.type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("true", "1", "yes", "on"):
                return True
            if lowered in ("false", "0", "no", "off"):
                return False
        return value
    if flag.type == "number":
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            text = value.strip()
            try:
                return int(text)
            except ValueError:
                try:
                    return float(text)
                except ValueError:
                    return value
        return value
    # string / enum / path
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return value


def normalize_flags(values: dict) -> dict:
    """Bring a stored {flag_key: value} dict up to the current schema:
    apply FLAG_RENAMES and coerce values to the declared types. Keys not in
    the schema are kept untouched (build_args ignores them), so a preset
    from a newer LlamaPanel loses nothing on an older one."""
    schema_by_key = {f.key: f for f in FLAG_SCHEMA}
    out: dict = {}
    for key, value in values.items():
        seen = {key}
        while key in FLAG_RENAMES and FLAG_RENAMES[key] not in seen:
            key = FLAG_RENAMES[key]
            seen.add(key)
        flag = schema_by_key.get(key)
        out[key] = _coerce_value(flag, value) if flag is not None else value
    return out


def build_args(model_entry_path: str, values: dict) -> list[str]:
    """Turn {flag_key: value} into a llama-server argv list."""
    args: list[str] = ["--model", model_entry_path]
    schema_by_key = {f.key: f for f in FLAG_SCHEMA}

    for key, value in values.items():
        flag = schema_by_key.get(key)
        if flag is None or value in (None, ""):
            continue
        if flag.type == "boolean":
            if bool(value):
                args.append(flag.cli)
        else:
            args.extend([flag.cli, str(value)])

    return args
