import re
from typing import Optional, TypedDict

import psutil

from app.flags import FLAG_SCHEMA
from app.schemas import FlagValue


class DiscoveredProcess(TypedDict):
    pid: int
    model_path: Optional[str]
    flags: dict[str, FlagValue]


def _coerce(flag_type: str, raw: str) -> FlagValue:
    if flag_type != "number":
        return raw
    try:
        return int(raw)
    except ValueError:
        try:
            return float(raw)
        except ValueError:
            return raw


def _binary_key(path_or_name: str) -> str:
    """'C:\\llama\\llama-server.exe', 'llama-server.exe' and 'llama-server'
    all identify the same binary. Both separators are handled explicitly:
    pathlib on POSIX treats a backslash as an ordinary character, so a
    Windows-style server_bin would otherwise never match there."""
    return re.split(r"[\\/]", path_or_name)[-1].lower().removesuffix(".exe")


def find_running_llama_server(server_bin: str) -> Optional[DiscoveredProcess]:
    """Scan OS processes for one whose executable matches `server_bin` and
    reconstruct (model_path, flags) from its argv. Used to adopt a process
    we didn't spawn ourselves this run - started manually, or left over
    from a previous instance of this panel that has since exited.

    Blocking: call from a worker thread, never directly on the event loop.
    """
    target = _binary_key(server_bin)
    cli_to_flag = {f.cli: f for f in FLAG_SCHEMA}

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

            model_path: Optional[str] = None
            flags: dict[str, FlagValue] = {}
            i = 1
            while i < len(cmdline):
                token = cmdline[i]
                if token in ("--model", "-m") and i + 1 < len(cmdline):
                    model_path = cmdline[i + 1]
                    i += 2
                    continue
                flag = cli_to_flag.get(token)
                if flag is None:
                    i += 1
                    continue
                if flag.type == "boolean":
                    flags[flag.key] = True
                    i += 1
                elif i + 1 < len(cmdline):
                    flags[flag.key] = _coerce(flag.type, cmdline[i + 1])
                    i += 2
                else:
                    i += 1

            return {"pid": proc.info["pid"], "model_path": model_path, "flags": flags}
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    return None
