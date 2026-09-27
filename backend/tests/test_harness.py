import asyncio
import json
import sys

import psutil
import pytest
from pydantic import ValidationError

from app.evals.harness import HarnessRuntime
from app.evals.schemas import EvalParticipant, EvalRequest, ResumeRequest
from tests.test_evaluations import service  # shared fake model runtime


def request(**kwargs):
    return EvalRequest(
        name="Harness",
        engine="lm-eval",
        benchmarks=["gsm8k"],
        participants=[EvalParticipant(preset="A", concurrency=2)],
        **kwargs
    )


def test_harness_validation():
    assert request().harness.num_fewshot is None
    for options in (
        {"benchmarks": ["../custom"]},
        {"benchmarks": ["wikitext"]},
        {"participants": [{"preset": "A", "calibrate": True}]},
        {"harness": {"max_length": 512}},
    ):
        data = request().model_dump()
        data.update(options)
        with pytest.raises(ValidationError):
            EvalRequest.model_validate(data)


def test_harness_status_and_missing_engine(client):
    assert client.get("/api/evaluations/harness").json()["state"] == "missing"
    response = client.post("/api/evaluations/runs", json=request().model_dump())
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_harness_recovery_normalization_and_lease(service, monkeypatch):
    svc = service
    monkeypatch.setattr(svc.harness, "require", lambda: None)
    attempts = []

    async def worker(payload, directory, on_event):
        assert svc.app.state.instances.eval_active
        if payload.get("prepare"):
            assert svc.instance_id is None
            await on_event({"prepared": 1})
            return None
        attempts.append(payload["participant"]["effective_concurrency"])
        if len(attempts) == 1:
            return {"resource": True, "message": "CUDA out of memory"}
        directory.mkdir(parents=True, exist_ok=True)
        result = {
            "results": {
                "gsm8k": {
                    "exact_match,strict": 1.0,
                    "exact_match_stderr,strict": 0.0,
                    "exact_match,flexible": 1.0,
                }
            },
            "samples": {
                "gsm8k": [
                    {
                        "doc_id": 0,
                        "filter": "strict",
                        "target": "2",
                        "exact_match": 1,
                        "metrics": ["exact_match"],
                        "arguments": ["1+1"],
                        "resps": ["2"],
                    }
                ]
            },
        }
        (directory / "results.json").write_text(json.dumps(result))
        return None

    monkeypatch.setattr(svc.harness, "worker", worker)
    await svc.start(request())
    for _ in range(200):
        if svc.run["state"] == "paused":
            break
        await asyncio.sleep(0.01)
    assert svc.run["state"] == "paused"
    await svc.resume(ResumeRequest(concurrency=1))
    await svc.task
    assert svc.run["state"] == "completed", svc.run.get("error")
    assert attempts == [2, 1]
    assert svc.run["completed"] == svc.run["total"] == 1
    assert len(svc.run["metrics"]) == 2
    assert svc.results(svc.run["id"])[0]["status"] == "passed"
    assert not svc.app.state.instances.eval_active


@pytest.mark.asyncio
async def test_prepare_failure_does_not_stop_existing_servers(service, monkeypatch):
    svc = service
    monkeypatch.setattr(svc.harness, "require", lambda: None)
    manager = svc.app.state.instances.managers["default"]
    manager._state = "running"

    async def worker(*args):
        return {"message": "Dataset unavailable", "resource": False}

    monkeypatch.setattr(svc.harness, "worker", worker)
    await svc.start(request(stop_instances=["default"]))
    await svc.task
    assert svc.run["state"] == "failed"
    assert manager.state == "running"
    assert not svc.app.state.instances.eval_active


@pytest.mark.asyncio
async def test_worker_cancel_terminates_process(tmp_path, monkeypatch):
    runtime = HarnessRuntime(tmp_path)
    runtime.python = sys.executable
    monkeypatch.setattr(runtime, "require", lambda: None)
    original = asyncio.create_subprocess_exec
    started = asyncio.Event()
    child = None

    async def launch(*args, **kwargs):
        nonlocal child
        child = await original(
            sys.executable,
            "-u",
            "-c",
            "import time; print('LLAMAPANEL_EVENT {\"ready\": true}', flush=True); time.sleep(60)",
            **kwargs
        )
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)

    async def event(data):
        started.set()

    task = asyncio.create_task(runtime.worker({}, tmp_path / "run", event))
    await asyncio.wait_for(started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert child.returncode is not None
    assert not psutil.pid_exists(child.pid)
