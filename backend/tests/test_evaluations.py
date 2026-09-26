import asyncio
import json
from types import SimpleNamespace
import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from app.evals.library import BenchmarkLibrary, document
from app.evals.runner import (
    EvaluationService,
    ResourceError,
    numeric_score,
    select_samples,
)
from app.evals.schemas import EvalParticipant, EvalRequest, EvalSuite, ResumeRequest
from app.main import create_app
from app.process_manager import ProcessManager


def suite(scorer="exact_match"):
    return EvalSuite(
        name="Tiny",
        scorer=scorer,
        rubric="Rate memory from 0 to 5" if scorer == "local_judge" else "",
        samples=[
            {"id": str(i), "turns": [f"Question {i}"], "answer": "ok"} for i in range(5)
        ],
    )


def test_validation_and_sampling():
    base = {"name": "Test", "participants": [{"preset": "A"}], "benchmarks": ["x"]}
    for args in (
        {"sample_selection": "custom"},
        {"sample_limit": 2},
        {"sample_selection": "custom", "sample_limit": 0},
    ):
        with pytest.raises(ValidationError):
            EvalRequest(**base, **args)
    assert (
        EvalRequest(**base, sample_selection="custom", sample_limit=2).sample_limit == 2
    )
    with pytest.raises(ValidationError):
        EvalParticipant(preset="A", concurrency=0)
    data = list(range(50))
    assert select_samples(data, 7, 42) == select_samples(data, 7, 42)
    assert select_samples(data, 7, 42) != select_samples(data, 7, 43)
    assert select_samples(data, 100, 42) == data
    assert numeric_score("Working 4 + 5\n#### 9", "9") == 1
    assert numeric_score("#### 1,200.00", "1200") == 1
    assert numeric_score("There are 9 apples", "9") == 0
    assert numeric_score("#### 9 extra text", "9") == 0


def test_library_integrity(tmp_path):
    lib = BenchmarkLibrary(tmp_path)
    first = lib.install(suite())
    assert first == lib.install(suite())
    edited = suite()
    edited.samples[0].answer = "different"
    assert first != lib.install(edited)
    assert len(lib.list()) == 2
    path = lib.directory / f"{first}.json"
    data = json.loads(path.read_text())
    data["benchmark"]["suite"]["samples"][0]["answer"] = "tampered"
    path.write_text(json.dumps(data))
    with pytest.raises(HTTPException):
        lib.get(first)
    with pytest.raises(HTTPException):
        lib.get("../../outside")
    lib.set_directory(str(tmp_path / "elsewhere"))
    assert lib.list() == [] and path.exists()


def test_import_validation(client):
    assert (
        client.post(
            "/api/evaluations/library/import", json=suite().model_dump()
        ).status_code
        == 200
    )
    body = suite().model_dump()
    body["python"] = "print(1)"
    assert client.post("/api/evaluations/library/import", json=body).status_code == 422
    body = suite("local_judge").model_dump()
    body["rubric"] = ""
    assert client.post("/api/evaluations/library/import", json=body).status_code == 422


@pytest.fixture
async def service(settings, monkeypatch):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        svc = app.state.evaluations

        async def snapshot(p):
            return {
                **p.model_dump(),
                "model": {"id": p.preset, "entry_path": "fake.gguf"},
                "files": [],
                "flags": {},
                "binary": "fake",
                "effective_concurrency": p.concurrency,
                "calibration": [],
            }

        monkeypatch.setattr(svc, "snapshot", snapshot)

        async def start(m, model_id, binary, args, flags):
            m._state = "running"
            m._model_id = model_id
            m._flags = flags

        async def stop(m, *args, **kwargs):
            m._state = "stopped"

        monkeypatch.setattr(ProcessManager, "start", start)
        monkeypatch.setattr(ProcessManager, "stop", stop)
        yield svc


@pytest.mark.asyncio
async def test_sequential_comparison_and_local_judge(service, monkeypatch):
    svc = service
    id = svc.library.install(suite("local_judge"))
    order = []
    concurrent = 0
    maximum = 0

    async def chat(client, url, p, messages, seed):
        nonlocal concurrent, maximum
        order.append(p["preset"])
        concurrent += 1
        maximum = max(maximum, concurrent)
        await asyncio.sleep(0.001)
        concurrent -= 1
        return ('{"score":4,"reason":"ok"}' if p["preset"] == "judge" else "ok"), 5

    monkeypatch.setattr(svc, "chat", chat)
    await svc.start(
        EvalRequest(
            name="A/B",
            participants=[
                EvalParticipant(preset="A", concurrency=2),
                EvalParticipant(preset="B"),
            ],
            benchmarks=[id],
            sample_selection="custom",
            sample_limit=3,
            judge=EvalParticipant(preset="judge"),
        )
    )
    await svc.task
    assert svc.run["state"] == "completed", svc.run.get("error")
    assert svc.run["completed"] == 6 and svc.run["judge_completed"] == 6
    assert order == ["A"] * 3 + ["B"] * 3 + ["judge"] * 6 and maximum == 2
    assert all(m["score"] == 4 for m in svc.run["metrics"].values())
    assert (
        not svc.app.state.instances.eval_active
        and len(svc.app.state.instances.records) == 1
    )
    svc.library.remove(id)
    assert document(svc._dir(svc.run["id"]) / "inputs.json", "benchmarks").load()[0][
        "suite"
    ]["samples"]
    rows = svc.results(svc.run["id"])
    assert len(rows) == 12 and len({r["sample_id"] for r in rows}) == 3


@pytest.mark.asyncio
async def test_resource_retry_without_duplicates(service, monkeypatch):
    svc = service
    id = svc.library.install(suite())
    calls = 0

    async def chat(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ResourceError("out of memory")
        return "ok", 2

    monkeypatch.setattr(svc, "chat", chat)
    await svc.start(
        EvalRequest(
            name="Retry",
            participants=[EvalParticipant(preset="A", concurrency=2, ctx_size=8192)],
            benchmarks=[id],
        )
    )
    for _ in range(200):
        if svc.run["state"] == "paused":
            break
        await asyncio.sleep(0.005)
    assert svc.run["state"] == "paused"
    with pytest.raises(HTTPException):
        await svc.resume(ResumeRequest(concurrency=3))
    await svc.resume(ResumeRequest(concurrency=1))
    await svc.task
    assert svc.run["state"] == "completed", svc.run.get("error")
    assert svc.run["participants"][0]["ctx_size"] == 8192 and svc.run["completed"] == 5
    assert len(svc.results(svc.run["id"])) == 5


@pytest.mark.asyncio
async def test_cancel_releases_runtime(service, monkeypatch):
    svc = service
    id = svc.library.install(suite())
    waiting = asyncio.Event()

    async def chat(*args):
        waiting.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(svc, "chat", chat)
    await svc.start(
        EvalRequest(
            name="Cancel", participants=[EvalParticipant(preset="A")], benchmarks=[id]
        )
    )
    await asyncio.wait_for(waiting.wait(), 2)
    await svc.cancel()
    assert (
        svc.run["state"] == "cancelled"
        and not svc.app.state.instances.eval_active
        and svc.instance_id is None
    )


@pytest.mark.asyncio
async def test_immediate_cancel(service):
    id = service.library.install(suite())
    await service.start(
        EvalRequest(
            name="Cancel", participants=[EvalParticipant(preset="A")], benchmarks=[id]
        )
    )
    await service.cancel()
    assert (
        service.run["state"] == "cancelled"
        and not service.app.state.instances.eval_active
    )


@pytest.mark.asyncio
async def test_stop_confirmation_and_lease(service, monkeypatch):
    svc = service
    id = svc.library.install(suite())
    registry = svc.app.state.instances
    registry.managers["default"]._state = "running"
    req = EvalRequest(
        name="Busy", participants=[EvalParticipant(preset="A")], benchmarks=[id]
    )
    with pytest.raises(HTTPException) as exc:
        await svc.start(req)
    assert (
        exc.value.status_code == 409
        and exc.value.detail["instances"][0]["id"] == "default"
    )
    assert registry.managers["default"].state == "running"

    async def chat(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr(svc, "chat", chat)
    req.stop_instances = ["default"]
    await svc.start(req)
    with pytest.raises(HTTPException):
        registry.ensure_not_evaluating()
    await svc.cancel()


@pytest.mark.asyncio
async def test_api_truncation_and_oom(service):
    p = {"max_tokens": 10, "temperature": 0}
    for response, expected in [
        (httpx.Response(500, text="CUDA out of memory"), ResourceError),
        (
            httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": "partial"}, "finish_reason": "length"}
                    ]
                },
            ),
            ValueError,
        ),
    ]:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: response)
        ) as client:
            with pytest.raises(expected):
                await service.chat(client, "http://local", p, [], 42)


def test_interrupted_run(settings):
    path = settings.data_dir / "evaluations" / ("a" * 32) / "run.json"
    document(path, "run").save({"id": "a" * 32, "state": "running", "created_at": 1})
    svc = EvaluationService(SimpleNamespace(state=SimpleNamespace(settings=settings)))
    assert svc.get("a" * 32)["state"] == "interrupted"


@pytest.mark.asyncio
async def test_real_snapshot_resolves_flags_and_preserves_preset(settings, monkeypatch):
    from app.introspection import BinaryInspector
    from app.presets import PresetStore
    from app.flags import FlagCatalog

    settings.models_dir.mkdir(parents=True)
    model = settings.models_dir / "model.gguf"
    model.write_bytes(b"GGUF")
    preset = PresetStore(settings.presets_file)
    preset.upsert(
        "A", "model", {"ctx_size": 4096, "batch_size": 128, "api_key": "secret"}
    )
    original = BinaryInspector.inspect

    def inspect(self, *args):
        return original(self, *args).model_copy(update={"error": None})

    monkeypatch.setattr(BinaryInspector, "inspect", inspect)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        result = await app.state.evaluations.snapshot(
            EvalParticipant(preset="A", concurrency=4, batch_size=64, ubatch_size=32)
        )
        assert result["flags"]["parallel"] == 4
        assert (
            result["flags"]["batch_size"] == 64 and result["flags"]["ubatch_size"] == 32
        )
        assert result["flags"]["ctx_size"] == 4096 and "api_key" not in result["flags"]
        assert preset.list()[0]["flags"]["batch_size"] == 128
        assert result["files"][0]["size"] == 4


@pytest.mark.asyncio
async def test_download_checks_hash_before_publication(tmp_path, monkeypatch):
    import app.evals.library as module

    real = httpx.AsyncClient

    def client(**kwargs):
        return real(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(200, content=b"bad payload")
            )
        )

    monkeypatch.setattr(module.httpx, "AsyncClient", client)
    lib = BenchmarkLibrary(tmp_path)
    with pytest.raises(ValueError, match="checksum"):
        await lib.download("gsm8k", {})
    assert lib.list() == []


@pytest.mark.asyncio
async def test_pause_waits_for_batch_and_does_not_launch_next(service, monkeypatch):
    svc = service
    id = svc.library.install(suite())
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def chat(*args):
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return "ok", 1

    monkeypatch.setattr(svc, "chat", chat)
    await svc.start(
        EvalRequest(
            name="Pause", participants=[EvalParticipant(preset="A")], benchmarks=[id]
        )
    )
    await entered.wait()
    await svc.pause()
    release.set()
    for _ in range(100):
        if svc.run["state"] == "paused":
            break
        await asyncio.sleep(0.005)
    assert svc.run["state"] == "paused" and calls == 1
    await svc.resume(ResumeRequest())
    await svc.task
    assert calls == 5 and svc.run["state"] == "completed"


@pytest.mark.asyncio
async def test_scaled_lora_file_snapshot(settings, monkeypatch):
    from app.introspection import BinaryInspector
    from app.presets import PresetStore

    settings.models_dir.mkdir(parents=True)
    (settings.models_dir / "model.gguf").write_bytes(b"GGUF")
    adapter = settings.models_dir / "adapter.gguf"
    adapter.write_bytes(b"adapter")
    PresetStore(settings.presets_file).upsert(
        "Adapted", "model", {"lora_scaled": [f"{adapter}:0.5"]}
    )
    original = BinaryInspector.inspect
    monkeypatch.setattr(
        BinaryInspector,
        "inspect",
        lambda self, *args: original(self, *args).model_copy(update={"error": None}),
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        result = await app.state.evaluations.snapshot(EvalParticipant(preset="Adapted"))
        assert any(f["path"] == str(adapter) for f in result["files"])
        assert result["flags"]["lora_scaled"] == [f"{adapter}:0.5"]
