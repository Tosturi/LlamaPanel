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
        key="flash_attn", cli="--flash-attn", type="boolean",
        label="Flash Attention", group="basic", default=True,
    ),
    FlagDef(
        key="host", cli="--host", type="string",
        label="Host", group="basic", default="127.0.0.1",
    ),
    FlagDef(
        key="port", cli="--port", type="number",
        label="Port", group="basic", default=8080,
    ),
    # --- advanced ---
    FlagDef(
        key="cache_type_k", cli="--cache-type-k", type="enum",
        label="KV Cache Type (K)", group="advanced",
        options=["f16", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1"],
    ),
    FlagDef(
        key="cache_type_v", cli="--cache-type-v", type="enum",
        label="KV Cache Type (V)", group="advanced",
        options=["f16", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1"],
    ),
    FlagDef(
        key="split_mode", cli="--split-mode", type="enum",
        label="Split Mode", group="advanced",
        options=["none", "layer", "row"],
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
]


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
