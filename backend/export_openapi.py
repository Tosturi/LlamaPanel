#!/usr/bin/env python3
"""Dump the API's OpenAPI schema as JSON.

    python export_openapi.py            # to stdout
    python export_openapi.py out.json   # to a file

The frontend's `npm run gen:api` feeds this into openapi-typescript to
produce src/api-types.ts, so the TypeScript types are derived from the
pydantic models instead of being maintained by hand.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.main import create_app  # noqa: E402
from app.settings import Settings  # noqa: E402


def main() -> None:
    # A Settings pointing nowhere in particular: create_app() has no side
    # effects until the lifespan runs, and we never run it here.
    schema = create_app(Settings(frontend_dist=Path("/nonexistent"))).openapi()
    payload = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)


if __name__ == "__main__":
    main()
