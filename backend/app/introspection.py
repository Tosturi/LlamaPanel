"""Ask the installed llama-server what it can do.

llama.cpp changes its command-line surface constantly: flags are added,
renamed, get a --no-* twin or change type from a bare switch to
[on|off|auto]. Keeping a hand-written list in sync is a losing game, so the
plan is to make the *binary* the source of truth: run `llama-server --help`
once, parse the output into structured arguments, and build the UI schema
from that. This module is the parsing half; it knows nothing about presets
or the UI.

The help format comes from common_arg::to_string() in llama.cpp's
common/arg.cpp and has been stable for a long time:

    ----- common params -----

    -t,    --threads N                      number of CPU threads (default: -1)
                                            (env: LLAMA_ARG_THREADS)
    -kvo,  --kv-offload, -nkvo, --no-kv-offload
                                            whether to enable KV cache offloading (default: enabled)

An entry starts at column 0 with a dash. Its spellings are comma-separated,
followed by zero or more value hints (N, FNAME, [on|off|auto], ...). The
help text begins after at least two spaces on the same line when the head
fits in 37 columns, otherwise on the next line; continuation lines are
indented by 40 spaces and the text is word-wrapped at ~70 columns, so a
"(default: ...)" note can straddle two lines. Sections are `----- name -----`
banners. tests/fixtures/llama_server_help.txt is a real snapshot.

Everything derived here (type, default, options) is a best-effort
inference from free text and is meant to be refined by a curated overlay
in flags.py, not trusted blindly.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.schemas import BinaryInfo, FlagType, FlagValue, LlamaArg

PROBE_TIMEOUT_S = 20

_SECTION_RE = re.compile(r"^-{3,}\s*(?P<name>.+?)\s*-{3,}\s*$")
# "<spellings> [hints]   help": spellings are dash-prefixed tokens separated
# by ", " (with extra padding after the first one), hints are the following
# space-separated tokens, and the help text starts after a run of >= 2 spaces.
_HEAD_RE = re.compile(
    r"^(?P<args>-[^\s,]+(?:,\s+-[^\s,]+)*)"
    r"(?P<hints>(?: [^\s]+)*?)"
    r"(?:\s{2,}(?P<help>\S.*?))?\s*$"
)
_ENV_RE = re.compile(r"^\(env:\s*(?P<env>[A-Za-z_][A-Za-z0-9_]*)\)$")
# Usually "(default: 4096)", but also ", default: 'auto')" inside a longer
# parenthetical, so don't insist on the opening paren. Matched against the
# help text with line wraps undone.
_DEFAULT_RE = re.compile(r"default:\s*(?P<value>[^)]*)\)")
_ALLOWED_RE = re.compile(r"allowed values:\s*(?P<values>[^\n]+)")
_BULLET_RE = re.compile(r"^-\s+(?P<name>[A-Za-z0-9][A-Za-z0-9+_.-]*)(?:\s+\(default\))?:\s")
_REPEATABLE_RE = re.compile(
    r"can be repeated|may be specified multiple times|can be specified multiple times|"
    r"comma-separated (?:values|list)|use comma-separated",
    re.I,
)
_DEPRECATED_RE = re.compile(r"DEPRECATED|has been removed", re.I)
_VERSION_RE = re.compile(r"version:\s*(?P<build>\d+)\s*\((?P<commit>[^)]*)\)")
_NUMBER_RE = re.compile(r"^[-+]?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?$")
_RANGE_HINT_RE = re.compile(r"^<-?\d+\.{2,}-?\d+>$")  # <0...100>
_WORD_LIST_HINT_RE = re.compile(r"^[a-z][a-z0-9_-]*(,[a-z][a-z0-9_-]*)+$")  # none,draft-simple,...
_PATH_HINT_RE = re.compile(r"^[A-Z_]*(FNAME|PATH|FILE|DIR)$")

# Continuation lines are indented by 40 spaces in practice; accept anything
# clearly indented so a future width tweak doesn't silently drop help text.
_MIN_CONTINUATION_INDENT = 8
# Lines that start a new paragraph in the displayed help; everything else
# is treated as a soft wrap of the previous line.
_PARAGRAPH_START_RE = re.compile(r"^(-\s|\(|\[\(|allowed values:|note:|example:|types:|see |list of |available )")


@dataclass
class RawArg:
    """One `--help` entry before any type inference."""

    args: list[str]
    hints: list[str]
    help_lines: list[str] = field(default_factory=list)
    section: str = ""


class HelpParseError(ValueError):
    """The output didn't look like llama-server's --help at all."""


# --- parsing -----------------------------------------------------------------

def parse_help(text: str) -> list[RawArg]:
    """Split raw `--help` output into entries. Anything outside a section
    banner (usage line, examples) is ignored."""
    entries: list[RawArg] = []
    section: Optional[str] = None
    current: Optional[RawArg] = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line:
            # A blank line ends an entry - unless it is an *indented* blank,
            # which llama.cpp emits for an empty line inside a help string.
            if not (current is not None and len(raw_line) >= _MIN_CONTINUATION_INDENT):
                current = None
            continue
        m = _SECTION_RE.match(line)
        if m:
            section = m.group("name").strip()
            current = None
            continue
        if section is None:
            continue
        if line.startswith("-"):
            m = _HEAD_RE.match(line)
            if not m:
                current = None
                continue
            current = RawArg(
                args=[a.strip() for a in m.group("args").split(",")],
                hints=m.group("hints").split(),
                section=section,
            )
            if m.group("help"):
                current.help_lines.append(m.group("help"))
            entries.append(current)
            continue
        indent = len(line) - len(line.lstrip(" "))
        if current is not None and indent >= _MIN_CONTINUATION_INDENT:
            current.help_lines.append(line.strip())
            continue
        # A non-indented line that isn't an entry (e.g. "example usage:")
        # ends the current entry.
        current = None

    if not entries:
        raise HelpParseError("no option entries found in --help output")
    return entries


# --- inference ---------------------------------------------------------------

def _to_key(long_arg: str) -> str:
    return long_arg.lstrip("-").replace("-", "_")


def _split_negations(args: list[str]) -> tuple[list[str], list[str]]:
    """Separate `--no-X` spellings whose positive `--X` is also listed.
    A standalone `--no-host` stays a positive flag of its own."""
    longs = [a for a in args if a.startswith("--")]
    neg_longs = {a for a in longs if a.startswith("--no-") and f"--{a[len('--no-'):]}" in longs}
    if not neg_longs:
        return list(args), []
    # llama.cpp prints positive spellings first, then the negative ones
    # (-kvo, --kv-offload, -nkvo, --no-kv-offload): everything after the
    # last positive long form is the negative side, short forms included.
    # (--mmproj-auto, --no-mmproj, --no-mmproj-auto: --no-mmproj is an
    # extra negative alias even though no --mmproj is listed.)
    last_pos = max(i for i, a in enumerate(args) if a.startswith("--") and not a.startswith("--no-"))
    return list(args[: last_pos + 1]), list(args[last_pos + 1:])


def _split_env(lines: list[str]) -> tuple[list[str], Optional[str]]:
    env = None
    kept: list[str] = []
    for line in lines:
        m = _ENV_RE.match(line)
        if m:
            env = m.group("env")
        else:
            kept.append(line)
    return kept, env


def _reflow(lines: list[str]) -> str:
    """Undo the 70-column word wrap for display: consecutive lines are one
    paragraph unless a line clearly starts a new one (bullet, parenthetical
    note, "allowed values:", ...)."""
    paragraphs: list[str] = []
    for line in lines:
        if not line:
            paragraphs.append("")
        elif paragraphs and paragraphs[-1] and not _PARAGRAPH_START_RE.match(line):
            paragraphs[-1] = f"{paragraphs[-1]} {line}"
        else:
            paragraphs.append(line)
    text = "\n".join(paragraphs).strip()
    return re.sub(r"\n{2,}", "\n", text)


def _parse_scalar(text: str) -> FlagValue:
    value = text.strip().strip("'\"")
    if _NUMBER_RE.match(value):
        try:
            return int(value)
        except ValueError:
            return float(value)
    return value


def _enum_options(hints: list[str], help_lines: list[str]) -> Optional[list[str]]:
    for hint in hints:
        if hint.startswith("[") and hint.endswith("]") and "|" in hint:
            return hint[1:-1].split("|")
        if hint.startswith("<") and hint.endswith(">") and "|" in hint:
            return hint[1:-1].split("|")
        if hint.startswith("{") and hint.endswith("}") and "," in hint:
            return [o.strip() for o in hint[1:-1].split(",")]
        if _WORD_LIST_HINT_RE.match(hint):
            return hint.split(",")
    for line in help_lines:
        m = _ALLOWED_RE.search(line)
        if m:
            options = [o.strip() for o in m.group("values").split(",")]
            if all(options) and len(options) > 1:
                return options
    # "- auto: ...", "- mmap: ..." bullets under a MODE/TYPE/FORMAT hint
    # (not N: "--verbosity N" lists numeric levels the same way).
    if len(hints) == 1 and len(hints[0]) > 1 and hints[0].isupper() and hints[0].isalpha():
        bullets = [m.group("name") for m in (_BULLET_RE.match(l) for l in help_lines) if m]
        if len(bullets) >= 2:
            return bullets
    return None


def _infer_type(hints: list[str], options: Optional[list[str]], default: Optional[FlagValue]) -> FlagType:
    if not hints:
        return "boolean"
    if options:
        return "enum"
    if len(hints) != 1:
        return "string"
    hint = hints[0]
    is_numeric_default = isinstance(default, (int, float)) and not isinstance(default, bool)
    if hint == "N" or _RANGE_HINT_RE.match(hint):
        # "-ngl N ... (default: auto)" accepts words too; a text default
        # means the field can't be a pure number input.
        return "string" if isinstance(default, str) else "number"
    if _PATH_HINT_RE.match(hint):
        return "path"
    # PORT, SECONDS, INDEX, ...: a plain uppercase hint whose default is a
    # number is almost certainly numeric.
    if hint.isupper() and hint.isalpha() and is_numeric_default:
        return "number"
    return "string"


def _boolean_default(default_text: Optional[str], has_pair: bool) -> Optional[bool]:
    # A standalone switch (--no-host) is simply absent unless set. Only a
    # positive/negative pair has a meaningful "enabled by default".
    if not has_pair:
        return False
    if default_text is None:
        return None
    lowered = default_text.split(",", 1)[0].strip().strip("'\"").lower()
    if lowered in ("enabled", "true", "on", "1", "yes"):
        return True
    if lowered in ("disabled", "false", "off", "0", "no"):
        return False
    # "prefill enabled", "enabled if number of slots is auto"
    if "disabled" in lowered:
        return False
    if lowered.endswith("enabled"):
        return True
    return None


_UNSET_DEFAULTS = ("none", "unused", "disabled", "empty", "unset", "")


def _value_default(default_text: Optional[str], options: Optional[list[str]]) -> Optional[FlagValue]:
    """Default of a value-taking flag from its "(default: ...)" note.
    "(default: -1, use random seed for -1)" yields -1; prose like
    "(default: same as --threads)" yields None; "(default: none)" is None
    unless "none" is a real enum option."""
    if default_text is None:
        return None
    text = default_text.strip()
    if options is not None:
        first = re.split(r"[\s,;]+", text.strip("'\""), maxsplit=1)[0].strip("'\"")
        return first if first in options else None
    # A numeric default is often followed by an explanation: "-1, -1 = auto",
    # "-1; -1 = disabled". A textual one may itself contain commas
    # ("GET, POST, DELETE, OPTIONS") and is kept whole.
    head = re.split(r"[,;]\s", text, maxsplit=1)[0]
    if _NUMBER_RE.match(head.strip("'\"")):
        return _parse_scalar(head)
    if head.strip("'\"").lower() in _UNSET_DEFAULTS:  # "unset, behavior unchanged"
        return None
    parsed = _parse_scalar(text)
    if isinstance(parsed, str) and (parsed.lower() in _UNSET_DEFAULTS or (" " in parsed and ", " not in parsed)):
        return None
    return parsed


def to_llama_arg(raw: RawArg) -> LlamaArg:
    pos, neg = _split_negations(raw.args)
    long_args = [a for a in pos if a.startswith("--")]
    if not long_args:
        # Short-only entries don't exist in practice; fall back so nothing is lost.
        long_args = pos[:1]
    key = _to_key(long_args[0])

    lines, env = _split_env(raw.help_lines)
    flat_help = " ".join(l for l in lines if l)
    default_matches = list(_DEFAULT_RE.finditer(flat_help))
    default_text = default_matches[-1].group("value") if default_matches else None

    options = _enum_options(raw.hints, lines)
    if not raw.hints:
        default = _boolean_default(default_text, bool(neg))
    else:
        default = _value_default(default_text, options)

    return LlamaArg(
        key=key,
        args=pos,
        args_neg=neg,
        value_hints=raw.hints,
        type=_infer_type(raw.hints, options, default),
        options=options,
        default=default,
        help=_reflow(lines),
        env=env,
        section=raw.section,
        repeatable=bool(_REPEATABLE_RE.search(flat_help)),
        deprecated=bool(_DEPRECATED_RE.search(flat_help)),
    )


def parse_help_to_args(text: str) -> list[LlamaArg]:
    out: list[LlamaArg] = []
    seen: set[str] = set()
    for raw in parse_help(text):
        arg = to_llama_arg(raw)
        # llama.cpp lists a handful of options twice (once per section they
        # belong to); the first occurrence wins.
        if arg.key in seen:
            continue
        seen.add(arg.key)
        out.append(arg)
    return out


def parse_version(text: str) -> tuple[Optional[int], Optional[str]]:
    m = _VERSION_RE.search(text)
    if not m:
        return None, None
    commit = m.group("commit").strip() or None
    return int(m.group("build")), commit


# --- running the binary ------------------------------------------------------

def resolve_binary(server_bin: str) -> Optional[Path]:
    """Absolute path of the configured binary, or None if it can't be found
    (neither an existing path nor on PATH)."""
    candidate = Path(server_bin).expanduser()
    if candidate.is_file():
        return candidate.resolve()
    found = shutil.which(server_bin)
    return Path(found).resolve() if found else None


def _run(binary: Path, *args: str) -> str:
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(
        [str(binary), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        timeout=PROBE_TIMEOUT_S,
        text=True,
        encoding="utf-8",
        errors="replace",
        **kwargs,
    )
    return proc.stdout


class BinaryInspector:
    """Probes the llama-server binary and caches the result until the file
    on disk changes (path, size or mtime), so the UI can ask as often as
    it likes and a `llama.cpp` upgrade is picked up without restarting
    the panel. Safe to call from multiple threads."""

    def __init__(self, server_bin: str) -> None:
        self.server_bin = server_bin
        self._lock = threading.Lock()
        self._cache_key: Optional[tuple] = None
        self._cache: Optional[BinaryInfo] = None

    def _fingerprint(self, path: Optional[Path]) -> tuple:
        if path is None:
            return (None,)
        try:
            st = os.stat(path)
        except OSError:
            return (str(path),)
        return (str(path), st.st_size, st.st_mtime_ns)

    def inspect(self, force: bool = False) -> BinaryInfo:
        path = resolve_binary(self.server_bin)
        key = self._fingerprint(path)
        with self._lock:
            if not force and self._cache is not None and key == self._cache_key:
                return self._cache
            info = self._probe(path)
            self._cache, self._cache_key = info, key
            return info

    def _probe(self, path: Optional[Path]) -> BinaryInfo:
        if path is None:
            return BinaryInfo(
                server_bin=self.server_bin,
                resolved_path=None,
                error=f"'{self.server_bin}' not found: not an existing file and not on PATH",
            )
        build, commit, args, errors = None, None, [], []
        try:
            build, commit = parse_version(_run(path, "--version"))
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append(f"--version failed: {exc}")
        try:
            args = parse_help_to_args(_run(path, "--help"))
        except (OSError, subprocess.SubprocessError, HelpParseError) as exc:
            errors.append(f"--help failed: {exc}")
        return BinaryInfo(
            server_bin=self.server_bin,
            resolved_path=str(path),
            build=build,
            commit=commit,
            args=args,
            error="; ".join(errors) or None,
        )
