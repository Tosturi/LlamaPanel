"""Optional, isolated lm-evaluation-harness runtime and supervised workers."""

import asyncio
import json
import os
import sys

import psutil
from pathlib import Path

from fastapi import HTTPException

REVISION = "d6de81643928d653435c431bae19945d41d32520"
REQUIREMENT = f"lm_eval[api,ifeval] @ https://github.com/EleutherAI/lm-evaluation-harness/archive/{REVISION}.zip"
# Initial integration surface; HF catalog management is a separate feature.
TASKS = [
    {"id": "gsm8k", "type": "generate_until"},
    {"id": "ifeval", "type": "generate_until"},
    {"id": "arc_easy", "type": "multiple_choice"},
    {"id": "arc_challenge", "type": "multiple_choice"},
    {"id": "hellaswag", "type": "multiple_choice"},
    {"id": "winogrande", "type": "multiple_choice"},
    {"id": "boolq", "type": "multiple_choice"},
]


async def stop_process(process):
    if process.returncode is None:
        try:
            descendants = psutil.Process(process.pid).children(recursive=True)
        except psutil.NoSuchProcess:
            descendants = []
        for child in reversed(descendants):
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), 5)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
        for child in descendants:
            try:
                if child.is_running():
                    child.kill()
            except psutil.NoSuchProcess:
                pass


class HarnessRuntime:
    def __init__(self, data_dir):
        self.root = data_dir / "harness"
        self.python = (
            self.root
            / "venv"
            / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        )
        self.marker = self.root / "installed.json"
        self.task = None
        self.error = None

    def status(self):
        ready = False
        if self.marker.exists() and self.python.exists():
            try:
                ready = json.loads(self.marker.read_text())["revision"] == REVISION
            except (ValueError, KeyError):
                pass
        return {
            "state": (
                "installing"
                if self.task and not self.task.done()
                else "ready" if ready else "missing"
            ),
            "revision": REVISION,
            "error": self.error,
            "tasks": TASKS,
        }

    def require(self):
        if self.status()["state"] != "ready":
            raise HTTPException(
                409, "Install lm-evaluation-harness in Evaluations first"
            )

    def environment(self):
        env = os.environ.copy()
        env.update(
            HF_HOME=str(self.root / "hf-cache"),
            PYTHONUNBUFFERED="1",
            HF_DATASETS_TRUST_REMOTE_CODE="0",
            NLTK_DATA=str(self.root / "nltk-data"),
            OMP_NUM_THREADS="1",
            OPENBLAS_NUM_THREADS="1",
            TOKENIZERS_PARALLELISM="false",
        )
        # Only model HTTP requests bypass proxies, in the worker's Session.
        return env

    async def install(self):
        if self.task and not self.task.done():
            return

        async def perform():
            self.error = None
            self.root.mkdir(parents=True, exist_ok=True)
            (self.root / "nltk-data").mkdir(exist_ok=True)
            self.marker.unlink(missing_ok=True)
            try:
                with (self.root / "install.log").open("wb") as log:
                    for command in (
                        [sys.executable, "-m", "venv", str(self.root / "venv")],
                        [str(self.python), "-m", "pip", "install", REQUIREMENT],
                        [
                            str(self.python),
                            str(Path(__file__).with_name("harness_worker.py")),
                            "--check",
                        ],
                    ):
                        process = await asyncio.create_subprocess_exec(
                            *command, stdout=log, stderr=log, env=self.environment()
                        )
                        try:
                            if await process.wait():
                                raise RuntimeError(
                                    "Harness installation failed; see harness/install.log"
                                )
                        finally:
                            await stop_process(process)
                with (self.root / "packages.txt").open("wb") as packages:
                    process = await asyncio.create_subprocess_exec(
                        str(self.python),
                        "-m",
                        "pip",
                        "freeze",
                        stdout=packages,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    try:
                        if await process.wait():
                            raise RuntimeError(
                                "Cannot record harness dependency versions"
                            )
                    finally:
                        await stop_process(process)
                self.marker.write_text(
                    json.dumps({"revision": REVISION}), encoding="utf-8"
                )
            except asyncio.CancelledError:
                self.error = "Installation interrupted"
                raise
            except Exception as exc:
                self.error = str(exc)

        self.task = asyncio.create_task(perform())

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    async def worker(self, payload, directory, on_event):
        self.require()
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "error.json").unlink(missing_ok=True)
        config = directory / "worker.json"
        config.write_text(json.dumps(payload), encoding="utf-8")
        with (directory / "harness.log").open("ab") as log:
            process = await asyncio.create_subprocess_exec(
                str(self.python),
                str(Path(__file__).with_name("harness_worker.py")),
                str(config),
                stdout=asyncio.subprocess.PIPE,
                stderr=log,
                env=self.environment(),
                limit=1024 * 1024,
            )
            try:
                while line := await process.stdout.readline():
                    log.write(line)
                    log.flush()
                    if line.startswith(b"LLAMAPANEL_EVENT "):
                        await on_event(json.loads(line[len(b"LLAMAPANEL_EVENT ") :]))
                code = await process.wait()
                if code:
                    error_file = directory / "error.json"
                    error = (
                        json.loads(error_file.read_text())
                        if error_file.exists()
                        else {
                            "message": f"Harness exited with code {code}",
                            "resource": False,
                        }
                    )
                    return error
                return None
            finally:
                await stop_process(process)
