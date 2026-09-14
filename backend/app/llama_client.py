import json
import urllib.request
from urllib.error import HTTPError, URLError


def is_busy(host: str, port: int, timeout: float = 2.0) -> bool | None:
    """Ask the running llama-server's own /slots endpoint whether any slot is
    mid-generation. This works no matter who sent the request (Hermes, the
    llama.cpp webui, curl, ...) - llama-server tracks it itself, so callers
    of this panel never need to know or signal anything.

    Returns None if the check is inconclusive (server unreachable, or
    started with --no-slots) rather than guessing true/false.
    """
    query_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    try:
        with urllib.request.urlopen(f"http://{query_host}:{port}/slots", timeout=timeout) as resp:
            slots = json.loads(resp.read())
    except (URLError, HTTPError, TimeoutError, ValueError, OSError):
        return None
    if not isinstance(slots, list):
        return None
    return any(slot.get("is_processing") for slot in slots)
