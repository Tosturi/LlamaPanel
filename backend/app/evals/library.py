"""Content-addressed, validated datasets. Imported files never execute code."""

import hashlib
import json
from pathlib import Path

import httpx
from fastapi import HTTPException

from app.evals.schemas import EvalSuite, EvalSample
from app.storage import JsonDocumentStore

MAX_BYTES = 32 * 1024 * 1024
GSM_URL = "https://raw.githubusercontent.com/openai/grade-school-math/master/grade_school_math/data/test.jsonl"
GSM_SHA256 = "3730d312f6e3440559ace48831e51066acaca737f6eabec99bccb9e4b3c39d14"
CATALOG = [
    {
        "id": "gsm8k",
        "name": "GSM8K",
        "description": "Test split · 1,319 questions · zero-shot chat · numeric exact match",
        "source": "https://github.com/openai/grade-school-math",
        "license": "MIT",
        "download_bytes": 749738,
        "recipe": "llamapanel-gsm8k-zero-shot-v1",
    }
]


def document(path, key, empty=dict):
    return JsonDocumentStore(
        path, key=key, version=1, migrations={0: lambda x: x}, empty=empty
    )


class BenchmarkLibrary:
    def __init__(self, data_dir):
        self.config = document(data_dir / "eval-settings.json", "settings")
        self.default_directory = data_dir / "benchmarks"

    @property
    def directory(self):
        return Path(self.config.load().get("directory", str(self.default_directory)))

    def set_directory(self, value):
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise HTTPException(422, "Choose an absolute dataset directory")
        path.mkdir(parents=True, exist_ok=True)
        self.config.save({"directory": str(path.resolve())})

    def _path(self, id):
        if len(id) != 64 or any(c not in "0123456789abcdef" for c in id):
            raise HTTPException(404, "Benchmark not found")
        return self.directory / f"{id}.json"

    def get(self, id):
        path = self._path(id)
        if not path.exists():
            raise HTTPException(404, "Benchmark not installed")
        data = document(path, "benchmark").load()
        # Verify the snapshot before using a dataset modified outside the panel.
        digest = hashlib.sha256(
            json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        if digest != id:
            raise HTTPException(
                409, "Benchmark content changed; import it as a new revision"
            )
        EvalSuite.model_validate(data["suite"])
        return data

    def list(self):
        rows = []
        for path in sorted(self.directory.glob("*.json")):
            if len(path.stem) != 64:
                continue
            try:
                data = self.get(path.stem)
                suite = data["suite"]
                rows.append(
                    {
                        "id": path.stem,
                        "name": suite["name"],
                        "description": suite["description"],
                        "scorer": suite["scorer"],
                        "samples": len(suite["samples"]),
                        "bytes": path.stat().st_size,
                        "source": data["source"],
                        "recipe": data["recipe"],
                        "catalog_id": next(
                            (
                                c["id"]
                                for c in CATALOG
                                if data["source"].startswith(GSM_URL + "#")
                                and c["id"] == "gsm8k"
                            ),
                            None,
                        ),
                    }
                )
            except (ValueError, HTTPException) as exc:
                rows.append(
                    {
                        "id": path.stem,
                        "name": path.stem[:12],
                        "error": str(exc),
                        "samples": 0,
                    }
                )
        return rows

    def install(
        self, suite: EvalSuite, source="Local import", recipe="llamapanel-custom-v1"
    ):
        data = {"suite": suite.model_dump(), "source": source, "recipe": recipe}
        raw = json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
        if len(raw) > MAX_BYTES:
            raise HTTPException(413, "Benchmark exceeds 32 MiB")
        id = hashlib.sha256(raw).hexdigest()
        document(self._path(id), "benchmark").save(data)
        return id

    def remove(self, id):
        self._path(id).unlink(missing_ok=True)

    async def download(self, id, progress):
        if id != "gsm8k":
            raise HTTPException(404, "Unknown catalog entry")
        raw = bytearray()
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            async with client.stream("GET", GSM_URL) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_BYTES:
                        raise ValueError("Dataset exceeds 32 MiB")
                    progress["bytes"] = len(raw)
        if hashlib.sha256(raw).hexdigest() != GSM_SHA256:
            raise ValueError("Dataset checksum mismatch; catalog update required")
        samples = []
        for i, line in enumerate(raw.decode().splitlines()):
            row = json.loads(line)
            samples.append(
                EvalSample(
                    id=str(i),
                    turns=[
                        row["question"]
                        + "\nSolve step by step. End with: #### <number>"
                    ],
                    answer=row["answer"].split("####")[-1].strip(),
                )
            )
        suite = EvalSuite(
            name="GSM8K",
            description=CATALOG[0]["description"],
            scorer="numeric",
            samples=samples,
        )
        import asyncio

        return await asyncio.to_thread(
            self.install, suite, f"{GSM_URL}#sha256={GSM_SHA256}", CATALOG[0]["recipe"]
        )
