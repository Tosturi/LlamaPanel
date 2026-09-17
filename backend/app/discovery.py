import re
from typing import Optional, TypedDict

import psutil

from app.flags import parse_args
from app.schemas import FlagDef, FlagValue


class DiscoveredProcess(TypedDict):
    pid: int
    model_path: Optional[str]
    flags: dict[str, FlagValue]


def _binary_key(path_or_name: str) -> str:
    """'C:\\llama\\llama-server.exe', 'llama-server.exe' and 'llama-server'
    all identify the same binary. Both separators are handled explicitly:
    pathlib on POSIX treats a backslash as an ordinary character, so a
    Windows-style server_bin would otherwise never match there."""
    return re.split(r"[\\/]", path_or_name)[-1].lower().removesuffix(".exe")


def find_running_llama_server(server_bin: str, schema: list[FlagDef]) -> Optional[DiscoveredProcess]:
    """Scan OS processes for one whose executable matches `server_bin` and
    reconstruct (model_path, flags) from its argv using `schema` (see
    flags.parse_args). Used to adopt a process we didn't spawn ourselves
    this run - started manually, or left over from a previous instance of
    this panel that has since exited.

    Blocking: call from a worker thread, never directly on the event loop.
    """
    target = _binary_key(server_bin)

    # Only `name` is requested up front: it comes from the OS's one-shot
    # process snapshot and is cheap for every process. `cmdline` is not - on
    # Windows psutil opens each process and reads its memory to get argv,
    # and with hundreds of processes (some of them protected, so the call
    # stalls on access checks) that used to be the whole cost of a scan.
    # Fetch it only for the handful of processes whose name matches.
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if _binary_key(proc.info["name"] or "") != target:
                continue
            cmdline = proc.cmdline() or []
            if not cmdline:
                continue
            model_path, flags = parse_args(cmdline, schema)
            return {"pid": proc.info["pid"], "model_path": model_path, "flags": flags}
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    return None
