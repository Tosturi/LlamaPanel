from pathlib import Path

# Single source of truth for the app version: the VERSION file at the repo
# root. The release workflow checks that the pushed tag matches it, the API
# exposes it via /api/health, and the UI shows it in the header.
_VERSION_FILE = Path(__file__).resolve().parents[2] / "VERSION"

try:
    __version__ = _VERSION_FILE.read_text(encoding="utf-8").strip() or "unknown"
except OSError:
    __version__ = "unknown"
