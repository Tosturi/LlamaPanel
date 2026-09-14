from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from app import config, discovery
from app.flags import FLAG_SCHEMA, build_args
from app.gguf_scanner import scan
from app.process_manager import manager
from app.schemas import FlagDef, RestartResponse, StartRequest, StatusResponse

router = APIRouter(prefix="/api/server", tags=["server"])


def _match_model_id(model_path: str | None) -> str | None:
    if not model_path:
        return None
    normalized = str(Path(model_path).resolve())
    for model in scan(config.MODELS_DIR):
        candidates = {str(Path(p.path).resolve()) for p in model.parts}
        candidates.add(str(Path(model.entry_path).resolve()))
        if normalized in candidates:
            return model.id
    return None


@router.get("/flags", response_model=list[FlagDef])
def get_flag_schema() -> list[FlagDef]:
    return FLAG_SCHEMA


@router.get("/status", response_model=StatusResponse)
async def get_status() -> StatusResponse:
    # If we don't think anything is running, check whether a llama-server is
    # actually alive out there (started manually, or left over from a
    # previous run of this panel) and adopt it so the UI reflects reality.
    if manager.state == "stopped":
        found = discovery.find_running_llama_server()
        if found:
            model_id = _match_model_id(found["model_path"])
            manager.adopt(pid=found["pid"], model_id=model_id, flags=found["flags"])
    return await manager.status()


@router.post("/start", response_model=StatusResponse)
async def start_server(req: StartRequest) -> StatusResponse:
    models = {m.id: m for m in scan(config.MODELS_DIR)}
    model = models.get(req.model_id)
    if model is None:
        raise HTTPException(status_code=404, detail=f"Model '{req.model_id}' not found")

    if manager.state in ("starting", "running"):
        raise HTTPException(status_code=409, detail=f"Server is already {manager.state}; stop it first")

    args = build_args(model.entry_path, req.flags)
    try:
        await manager.start(model_id=model.id, binary=config.LLAMA_SERVER_BIN, args=args, flags=req.flags)
    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail=f"'{config.LLAMA_SERVER_BIN}' binary not found. Set LLAMA_SERVER_BIN env var.",
        )
    return await manager.status()


@router.post("/stop", response_model=StatusResponse)
async def stop_server() -> StatusResponse:
    await manager.cancel_restart()
    await manager.stop()
    return await manager.status()


@router.post("/restart", response_model=RestartResponse)
async def restart_server(req: StartRequest) -> RestartResponse:
    """Apply new flags to the running server. Restarts immediately if it's
    idle; if llama-server reports an in-flight generation (via /slots), the
    restart is queued and applied automatically as soon as it finishes."""
    models = {m.id: m for m in scan(config.MODELS_DIR)}
    model = models.get(req.model_id)
    if model is None:
        raise HTTPException(status_code=404, detail=f"Model '{req.model_id}' not found")

    if manager.state not in ("running", "starting"):
        raise HTTPException(status_code=409, detail="Server is not running; use Start instead")

    args = build_args(model.entry_path, req.flags)
    try:
        result = await manager.restart(model_id=model.id, binary=config.LLAMA_SERVER_BIN, args=args, flags=req.flags)
    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail=f"'{config.LLAMA_SERVER_BIN}' binary not found. Set LLAMA_SERVER_BIN env var.",
        )
    return RestartResponse(result=result, status=await manager.status())


@router.post("/restart/cancel", response_model=StatusResponse)
async def cancel_restart() -> StatusResponse:
    await manager.cancel_restart()
    return await manager.status()


@router.websocket("/logs")
async def stream_logs(ws: WebSocket) -> None:
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
