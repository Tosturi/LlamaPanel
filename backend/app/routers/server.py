import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from app import discovery
from app.deps import ManagerDep, SettingsDep
from app.flags import FLAG_SCHEMA, build_args
from app.gguf_scanner import scan
from app.schemas import FlagDef, ModelInfo, RestartResponse, StartRequest, StatusResponse
from app.settings import Settings

router = APIRouter(prefix="/api/server", tags=["server"])


def _match_model_id(models_dir: Path, model_path: str | None) -> str | None:
    if not model_path:
        return None
    normalized = str(Path(model_path).resolve())
    for model in scan(models_dir):
        candidates = {str(Path(p.path).resolve()) for p in model.parts}
        candidates.add(str(Path(model.entry_path).resolve()))
        if normalized in candidates:
            return model.id
    return None


def _find_model(settings: Settings, model_id: str) -> ModelInfo:
    models = {m.id: m for m in scan(settings.models_dir)}
    model = models.get(model_id)
    if model is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    return model


def _binary_not_found(settings: Settings) -> HTTPException:
    return HTTPException(
        status_code=500,
        detail=f"'{settings.server_bin}' binary not found. Set server_bin in config.ini or LLAMAPANEL_SERVER_BIN.",
    )


@router.get("/flags", response_model=list[FlagDef])
def get_flag_schema() -> list[FlagDef]:
    return FLAG_SCHEMA


@router.get("/status", response_model=StatusResponse)
async def get_status(manager: ManagerDep, settings: SettingsDep) -> StatusResponse:
    # If we don't think anything is running, check whether a llama-server is
    # actually alive out there (started manually, or left over from a
    # previous run of this panel) and adopt it so the UI reflects reality.
    # The process scan and the model-directory scan are blocking I/O, and
    # the UI polls this endpoint every few seconds - run them off the event
    # loop so other requests (start, logs websocket) don't stall behind it.
    if manager.state == "stopped":
        found = await asyncio.to_thread(discovery.find_running_llama_server, settings.server_bin)
        # Re-check: a Start may have landed while the scan was running.
        if found and manager.state == "stopped":
            model_id = await asyncio.to_thread(_match_model_id, settings.models_dir, found["model_path"])
            if manager.state == "stopped":
                manager.adopt(pid=found["pid"], model_id=model_id, flags=found["flags"])
    return await manager.status()


@router.post("/start", response_model=StatusResponse)
async def start_server(req: StartRequest, manager: ManagerDep, settings: SettingsDep) -> StatusResponse:
    model = _find_model(settings, req.model_id)

    if manager.state in ("starting", "running"):
        raise HTTPException(status_code=409, detail=f"Server is already {manager.state}; stop it first")

    args = build_args(model.entry_path, req.flags)
    try:
        await manager.start(model_id=model.id, binary=settings.server_bin, args=args, flags=req.flags)
    except FileNotFoundError:
        raise _binary_not_found(settings)
    return await manager.status()


@router.post("/stop", response_model=StatusResponse)
async def stop_server(manager: ManagerDep) -> StatusResponse:
    await manager.cancel_restart()
    await manager.stop()
    return await manager.status()


@router.post("/restart", response_model=RestartResponse)
async def restart_server(req: StartRequest, manager: ManagerDep, settings: SettingsDep) -> RestartResponse:
    """Apply new flags to the running server. Restarts immediately if it's
    idle; if llama-server reports an in-flight generation (via /slots), the
    restart is queued and applied automatically as soon as it finishes."""
    model = _find_model(settings, req.model_id)

    if manager.state not in ("running", "starting"):
        raise HTTPException(status_code=409, detail="Server is not running; use Start instead")

    args = build_args(model.entry_path, req.flags)
    try:
        result = await manager.restart(model_id=model.id, binary=settings.server_bin, args=args, flags=req.flags)
    except FileNotFoundError:
        raise _binary_not_found(settings)
    return RestartResponse(result=result, status=await manager.status())


@router.post("/restart/cancel", response_model=StatusResponse)
async def cancel_restart(manager: ManagerDep) -> StatusResponse:
    await manager.cancel_restart()
    return await manager.status()


@router.websocket("/logs")
async def stream_logs(ws: WebSocket, manager: ManagerDep) -> None:
    await ws.accept()
    queue = manager.subscribe()
    try:
        while True:
            line = await queue.get()
            await ws.send_text(line)
    except WebSocketDisconnect:
        pass
    finally:
        manager.unsubscribe(queue)
