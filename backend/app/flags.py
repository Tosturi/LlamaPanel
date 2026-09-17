"""The flag schema the UI renders and the argv builder behind Start.

The schema is *derived* from the installed binary, not hand-written:
introspection.py parses `llama-server --help` into LlamaArg records, and
build_schema() turns them into FlagDef entries the frontend renders
generically. A small curated overlay (CURATED) adds what the help text
can't provide - a human label, which flags are "basic", a stable preset key
for options whose first spelling differs from the key older LlamaPanel
versions saved - and HIDDEN drops options the panel manages itself
(--model, --help, download shortcuts, log routing).

Presets store {key: value}. Because llama.cpp renames flags, every FlagDef
also carries all its spellings (`aliases`), and resolve_flags() matches a
stored key against any of them: a preset with `n_gpu_layers` finds the
flag whose spellings include --n-gpu-layers even if the binary now lists
--gpu-layers first. Keys that match nothing are kept in the preset and
reported as unsupported, so the UI can warn instead of silently dropping.

When the binary can't be probed at all, a snapshot of `--help` bundled with
the app (snapshots/llama-server-help.txt) stands in, so the panel still has
a complete form to show.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.introspection import BinaryInspector, parse_help_to_args
from app.schemas import FlagDef, FlagValue, LlamaArg

SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "llama-server-help.txt"

# Section order in the UI, then the help's own order within a section.
SECTION_ORDER = ("common params", "example-specific params", "sampling params", "speculative params")


@dataclass(frozen=True)
class Curated:
    """Overlay for one flag, matched by any of its CLI spellings."""

    match: tuple[str, ...]
    key: Optional[str] = None  # pin the preset key; default is derived from the first long spelling
    label: Optional[str] = None
    basic: bool = False


# Order here is the order in the UI within each group.
CURATED: tuple[Curated, ...] = (
    Curated(("--n-gpu-layers", "--gpu-layers"), key="n_gpu_layers", label="GPU Layers (-ngl)", basic=True),
    Curated(("--ctx-size",), label="Context Size", basic=True),
    Curated(("--kv-offload", "--no-kv-offload"), label="KV Cache Offload", basic=True),
    Curated(("--flash-attn",), label="Flash Attention", basic=True),
    Curated(("--host",), label="Host", basic=True),
    Curated(("--port",), label="Port", basic=True),
    Curated(("--seed",), label="Seed", basic=True),
    Curated(("--cache-type-k",), label="KV Cache Type (K)"),
    Curated(("--cache-type-v",), label="KV Cache Type (V)"),
    Curated(("--split-mode",), label="Split Mode"),
    Curated(("--mmproj",), label="Vision Projector"),
    Curated(("--override-tensor",), label="Override Tensor"),
    Curated(("--batch-size",), label="Batch Size"),
    Curated(("--threads",), label="CPU Threads"),
    Curated(("--spec-type",), label="Speculative Decoding Type"),
    Curated(("--spec-draft-n-max",), label="Max Draft Tokens"),
    Curated(("--parallel",), label="Server Slots"),
    Curated(("--tensor-split",), label="Tensor Split"),
    Curated(("--load-mode",), label="Model Load Mode"),
    Curated(("--api-key",), label="API Key"),
)

# Options the panel owns or that make no sense from a form. Matched by any
# spelling. --model is set from the selected model; the hf/docker/url
# family downloads weights and conflicts with it; logging goes to the
# panel's own log file; the *-default shortcuts pick a model for you.
HIDDEN: frozenset[str] = frozenset({
    "--help", "--usage", "--version", "--completion-bash", "--cache-list", "--list-devices",
    "--model", "--model-url", "--hf-repo", "--hf-file", "--hf-token", "--docker-repo",
    "--hf-repo-draft", "--spec-draft-hf",
    "--log-file", "--log-disable", "--log-colors",
    "--models-dir", "--models-preset",
    "--embd-gemma-default", "--fim-qwen-1.5b-default", "--fim-qwen-3b-default", "--fim-qwen-7b-default",
    "--fim-qwen-7b-spec", "--fim-qwen-14b-spec", "--fim-qwen-30b-default", "--gpt-oss-20b-default",
    "--gpt-oss-120b-default", "--vision-gemma-4b-default", "--vision-gemma-12b-default", "--spec-default",
})

# Old preset key -> current key, for renames that alias matching can't
# cover (the old spelling is gone from --help entirely). Chains are followed.
FLAG_RENAMES: dict[str, str] = {}


def key_from_cli(spelling: str) -> str:
    return spelling.lstrip("-").replace("-", "_")


# --- schema ------------------------------------------------------------------

def _curated_for(arg: LlamaArg) -> Optional[tuple[int, Curated]]:
    spellings = set(arg.args) | set(arg.args_neg)
    for i, c in enumerate(CURATED):
        if spellings & set(c.match):
            return i, c
    return None


def build_schema(args: list[LlamaArg]) -> list[FlagDef]:
    """LlamaArg records (from --help) -> the FlagDef list the UI renders.
    Curated flags come first in CURATED order; the rest follow grouped by
    section in SECTION_ORDER, keeping the help's order inside a section."""
    curated: list[tuple[int, FlagDef]] = []
    rest: list[tuple[int, int, FlagDef]] = []
    for position, arg in enumerate(args):
        if arg.deprecated or HIDDEN & (set(arg.args) | set(arg.args_neg)):
            continue
        hit = _curated_for(arg)
        long_args = [a for a in arg.args if a.startswith("--")] or arg.args
        cli = long_args[0]
        neg_long = [a for a in arg.args_neg if a.startswith("--")]
        flag = FlagDef(
            key=(hit[1].key if hit and hit[1].key else key_from_cli(cli)),
            cli=cli,
            cli_neg=neg_long[0] if neg_long else None,
            aliases=list(arg.args),
            aliases_neg=list(arg.args_neg),
            type=arg.type,
            label=(hit[1].label if hit and hit[1].label else cli),
            group="basic" if hit and hit[1].basic else "advanced",
            section=arg.section,
            default=arg.default,
            options=arg.options,
            help=arg.help or None,
            env=arg.env,
            repeatable=arg.repeatable,
        )
        if hit:
            curated.append((hit[0], flag))
        else:
            section_rank = SECTION_ORDER.index(arg.section) if arg.section in SECTION_ORDER else len(SECTION_ORDER)
            rest.append((section_rank, position, flag))
    curated.sort(key=lambda t: t[0])
    rest.sort(key=lambda t: (t[0], t[1]))
    return [f for _, f in curated] + [f for _, _, f in rest]


def bundled_schema() -> list[FlagDef]:
    """Schema from the --help snapshot shipped with the app."""
    return build_schema(parse_help_to_args(SNAPSHOT_PATH.read_text(encoding="utf-8")))


# --- matching preset keys to flags -------------------------------------------

@dataclass(frozen=True)
class _Index:
    by_key: dict[str, FlagDef]
    # Every long spelling, normalized to a key, -> (flag, is_negative_spelling).
    by_alias_key: dict[str, tuple[FlagDef, bool]]


def _index(schema: list[FlagDef]) -> _Index:
    by_key = {f.key: f for f in schema}
    by_alias_key: dict[str, tuple[FlagDef, bool]] = {}
    for f in schema:
        for negative, spellings in ((False, f.aliases), (True, f.aliases_neg)):
            for a in spellings:
                if a.startswith("--"):
                    by_alias_key.setdefault(key_from_cli(a), (f, negative))
    return _Index(by_key, by_alias_key)


def _lookup(index: _Index, key: str) -> Optional[tuple[FlagDef, bool]]:
    """Find the flag a stored key refers to: exact key, then any long
    spelling, then FLAG_RENAMES (chains followed, cycles tolerated)."""
    seen: set[str] = set()
    while True:
        if key in index.by_key:
            return index.by_key[key], False
        if key in index.by_alias_key:
            return index.by_alias_key[key]
        seen.add(key)
        nxt = FLAG_RENAMES.get(key)
        if nxt is None or nxt in seen:
            return None
        key = nxt


def _coerce_value(flag: FlagDef, value):
    """Best-effort conversion of a stored value to the type the schema now
    declares (a flag that changed from string to number, a boolean saved
    as "true", ...). Unknown or unconvertible values are returned as-is;
    None/"" mean "unset" and stay that way."""
    if value is None or value == "":
        return value
    if flag.repeatable and isinstance(value, list):
        return [_coerce_value(flag, v) for v in value]
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


def resolve_flags(values: dict, schema: list[FlagDef]) -> tuple[dict, list[str]]:
    """Bring stored {key: value} up to the given schema.

    Keys are matched by exact key, any long spelling or FLAG_RENAMES, and
    re-keyed to the flag's current key; a key that is the *negative*
    spelling of a boolean pair (`no_kv_offload: true`) becomes the positive
    key with the value inverted. Values are coerced to the declared type.

    Keys that match nothing are kept untouched and returned in the second
    element, so a preset saved against another llama.cpp build loses
    nothing and the UI can say which flags this build won't take."""
    index = _index(schema)
    out: dict = {}
    unsupported: list[str] = []
    for key, value in values.items():
        hit = _lookup(index, key)
        if hit is None:
            out[key] = value
            unsupported.append(key)
            continue
        flag, negative = hit
        value = _coerce_value(flag, value)
        if negative and flag.type == "boolean" and isinstance(value, bool):
            value = not value
        out[flag.key] = value
    return out, unsupported


def normalize_flags(values: dict, schema: list[FlagDef]) -> dict:
    return resolve_flags(values, schema)[0]


# --- argv --------------------------------------------------------------------

def _is_default(flag: FlagDef, value) -> bool:
    if flag.default is None:
        return False
    if isinstance(value, bool) or isinstance(flag.default, bool):
        return value is flag.default
    return str(value) == str(flag.default)


def build_args(model_entry_path: str, values: dict, schema: list[FlagDef]) -> list[str]:
    """Turn {flag_key: value} into a llama-server argv list.

    Values equal to the flag's documented default are left out: with a
    form that seeds every field from its default, the command line would
    otherwise carry a hundred no-op tokens. Booleans with a --no-* twin are
    emitted either way when they differ from the default (`--no-kv-offload`
    to switch an enabled-by-default feature off); a plain switch is only
    ever emitted when true. Repeatable flags accept a list and are emitted
    once per item. Keys not in the schema are ignored."""
    args: list[str] = ["--model", model_entry_path]
    by_key = {f.key: f for f in schema}

    for key, value in values.items():
        flag = by_key.get(key)
        if flag is None or value is None or value == "" or value == []:
            continue
        if flag.type == "boolean":
            enabled = bool(value)
            if _is_default(flag, enabled):
                continue
            if enabled:
                args.append(flag.cli)
            elif flag.cli_neg:
                args.append(flag.cli_neg)
            continue
        items = value if isinstance(value, list) else [value]
        for item in items:
            if item is None or item == "" or _is_default(flag, item):
                continue
            args.extend([flag.cli, str(item)])

    return args


def parse_args(argv: list[str], schema: list[FlagDef]) -> tuple[Optional[str], dict[str, FlagValue]]:
    """Inverse of build_args for a process we didn't start: (model_path,
    {key: value}) from argv, understanding every spelling incl. short and
    --no-* forms. Unknown tokens are skipped. argv[0] is the binary."""
    by_spelling: dict[str, tuple[FlagDef, bool]] = {}
    for f in schema:
        for negative, spellings in ((False, f.aliases), (True, f.aliases_neg)):
            for a in spellings:
                by_spelling.setdefault(a, (f, negative))

    model_path: Optional[str] = None
    flags: dict[str, FlagValue] = {}
    i = 1
    while i < len(argv):
        token = argv[i]
        if token in ("--model", "-m") and i + 1 < len(argv):
            model_path = argv[i + 1]
            i += 2
            continue
        hit = by_spelling.get(token)
        if hit is None:
            i += 1
            continue
        flag, negative = hit
        if flag.type == "boolean":
            flags[flag.key] = not negative
            i += 1
        elif i + 1 < len(argv):
            value = _coerce_value(flag, argv[i + 1])
            if flag.repeatable and flag.key in flags:
                prev = flags[flag.key]
                flags[flag.key] = (prev if isinstance(prev, list) else [prev]) + [value]  # type: ignore[assignment]
            else:
                flags[flag.key] = value
            i += 2
        else:
            i += 1
    return model_path, flags


# --- the live catalog --------------------------------------------------------

class FlagCatalog:
    """The schema for the *currently installed* llama-server, rebuilt when
    the inspector reports a different binary and falling back to the
    bundled snapshot when no binary can be probed."""

    def __init__(self, inspector: BinaryInspector) -> None:
        self._inspector = inspector
        self._lock = threading.Lock()
        self._built_from: Optional[int] = None
        self._schema: list[FlagDef] = []
        self.source: str = "none"  # "binary" | "bundled"

    def schema(self) -> list[FlagDef]:
        info = self._inspector.inspect()
        with self._lock:
            if self._built_from != id(info):
                if info.args:
                    self._schema, self.source = build_schema(info.args), "binary"
                else:
                    self._schema, self.source = bundled_schema(), "bundled"
                self._built_from = id(info)
            return self._schema

    def resolve(self, values: dict) -> tuple[dict, list[str]]:
        return resolve_flags(values, self.schema())

    def build_args(self, model_entry_path: str, values: dict) -> list[str]:
        return build_args(model_entry_path, values, self.schema())

    def parse_args(self, argv: list[str]) -> tuple[Optional[str], dict[str, FlagValue]]:
        return parse_args(argv, self.schema())
