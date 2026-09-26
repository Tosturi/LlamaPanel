import asyncio
import json

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import ValidationError

from app.evals.library import CATALOG, MAX_BYTES
from app.evals.schemas import EvalRequest, EvalStorage, EvalSuite, ResumeRequest

router = APIRouter(prefix="/api/evaluations", tags=["evaluations"])


def service(request):
    return request.app.state.evaluations


def idle(svc):
    if svc.active or (svc.download_task and not svc.download_task.done()):
        raise HTTPException(409, "Wait for the active evaluation or dataset download")


@router.get("/library")
async def library(request: Request) -> dict:
    svc = service(request)
    return {
        "directory": str(svc.library.directory),
        "installed": await asyncio.to_thread(svc.library.list),
        "catalog": CATALOG,
        "download": svc.download,
    }


@router.put("/library/storage")
async def storage(body: EvalStorage, request: Request) -> dict:
    svc = service(request)
    async with svc.lock:
        idle(svc)
        await asyncio.to_thread(svc.library.set_directory, body.directory)
    return {"directory": str(svc.library.directory)}


@router.post("/library/import")
async def import_suite(request: Request) -> dict:
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_BYTES:
            raise HTTPException(413, "Benchmark exceeds 32 MiB")
    try:
        suite = EvalSuite.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(422, str(exc))
    svc = service(request)
    async with svc.lock:
        idle(svc)
        id = await asyncio.to_thread(svc.library.install, suite)
    return {"id": id}


@router.post("/library/download/{id}")
async def download(id: str, request: Request) -> dict:
    svc = service(request)
    async with svc.lock:
        idle(svc)
        if id not in {c["id"] for c in CATALOG}:
            raise HTTPException(404, "Unknown benchmark")
        await svc.start_download(id)
    return svc.download


@router.post("/library/download-cancel")
async def cancel_download(request: Request) -> dict:
    svc = service(request)
    if svc.download_task and not svc.download_task.done():
        svc.download_task.cancel()
        await svc.download_task
    return svc.download


@router.delete("/library/{id}")
async def remove(id: str, request: Request) -> dict:
    svc = service(request)
    async with svc.lock:
        idle(svc)
        await asyncio.to_thread(svc.library.remove, id)
    return {"deleted": id}


@router.get("/runs")
async def runs(request: Request) -> list[dict]:
    return await asyncio.to_thread(service(request).list)


@router.get("/active")
async def active(request: Request) -> dict | None:
    svc = service(request)
    return svc.public_run() if svc.active else None


@router.post("/runs", status_code=201)
async def start(body: EvalRequest, request: Request) -> dict:
    return await service(request).start(body)


@router.get("/runs/{id}")
async def run(id: str, request: Request) -> dict:
    svc = service(request)
    value = await asyncio.to_thread(svc.get, id)
    for benchmark in value["benchmarks"]:
        if "samples" in benchmark["suite"]:
            benchmark["selected_ids"] = [
                s["id"] for s in benchmark["suite"].pop("samples")
            ]
    return value


@router.get("/runs/{id}/samples")
async def samples(
    id: str,
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[dict]:
    return await asyncio.to_thread(service(request).results, id, offset, limit)


@router.get("/runs/{id}/logs")
async def logs(id: str, request: Request) -> dict:
    svc = service(request)
    value = svc.get(id)
    instance_id = value.get("instance_id")
    if not instance_id:
        return {"text": ""}
    path = (
        request.app.state.settings.data_dir
        / "instances"
        / instance_id
        / "llama-server.log"
    )

    # Read only the tail; model loading logs may be large.
    def read():
        if not path.exists():
            return ""
        with path.open("rb") as f:
            f.seek(max(0, path.stat().st_size - 32000))
            return f.read().decode("utf-8", errors="replace")

    return {"text": await asyncio.to_thread(read)}


def require_active(svc, id):
    if not svc.active or svc.run["id"] != id:
        raise HTTPException(409, "Comparison is no longer active")


@router.post("/runs/{id}/pause")
async def pause(id: str, request: Request) -> dict:
    svc = service(request)
    require_active(svc, id)
    await svc.pause()
    return svc.public_run()


@router.post("/runs/{id}/resume")
async def resume(id: str, body: ResumeRequest, request: Request) -> dict:
    svc = service(request)
    require_active(svc, id)
    await svc.resume(body)
    return svc.public_run()


@router.post("/runs/{id}/cancel")
async def cancel(id: str, request: Request) -> dict:
    svc = service(request)
    require_active(svc, id)
    await svc.cancel()
    return svc.public_run()
