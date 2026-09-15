from pathlib import Path
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


def find_running_llama_server(server_bin: str) -> Optional[DiscoveredProcess]:
    """Scan OS processes for one whose executable matches `server_bin` and
    reconstruct (model_path, flags) from its argv. Used to adopt a process
    we didn't spawn ourselves this run - started manually, or left over
    from a previous instance of this panel that has since exited.
    """
    bin_name = Path(server_bin).name.lower()
    cli_to_flag = {f.cli: f for f in FLAG_SCHEMA}

    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = proc.info["cmdline"] or []
            if not cmdline or Path(cmdline[0]).name.lower() != bin_name:
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
