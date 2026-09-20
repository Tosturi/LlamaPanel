import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from app import discovery
from app.deps import CatalogDep, InspectorDep, ManagerDep, SettingsDep
from app.gguf_scanner import scan
from app.schemas import BinaryInfo, FlagDef, ModelInfo, RestartResponse, StartRequest, StatusResponse
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
async def get_flag_schema(catalog: CatalogDep) -> list[FlagDef]:
    """Form schema for the installed llama-server (from its --help), or
    from the bundled snapshot when the binary can't be probed."""
    # First call may run the binary; keep that off the event loop.
    return await asyncio.to_thread(catalog.schema)


@router.get("/binary", response_model=BinaryInfo)
async def get_binary_info(inspector: InspectorDep, refresh: bool = False) -> BinaryInfo:
    """Version and full option list of the configured llama-server, learned
    by running `--version` and `--help`. Cached until the binary on disk
    changes; `?refresh=true` forces a re-probe. Never fails: a missing or
    broken binary is reported in `error` with whatever else was learned."""
    return await asyncio.to_thread(inspector.inspect, refresh)


@router.get("/status", response_model=StatusResponse)
async def get_status(request: Request, manager: ManagerDep, settings: SettingsDep, catalog: CatalogDep) -> StatusResponse:
    # If we don't think anything is running, check whether a llama-server is
    # actually alive out there (started manually, or left over from a
    # previous run of this panel) and adopt it so the UI reflects reality.
    # The process scan and the model-directory scan are blocking I/O, and
    # the UI polls this endpoint every few seconds - run them off the event
    # loop so other requests (start, logs websocket) don't stall behind it.
    if request.query_params.get("instance_id", "default") == "default" and manager.state == "stopped":
        schema = await asyncio.to_thread(catalog.schema)
        found = await asyncio.to_thread(discovery.find_running_llama_server, settings.server_bin, schema)
        registry = request.app.state.instances
        async with registry.lock:
            # A process owned by another instance must never be adopted twice.
            if found and manager.state == "stopped" and not any(
                m is not manager and m._pid == found["pid"] for m in registry.managers.values()
            ):
                port = int(found["flags"].get("port") or 8080)
                if not any(r.id != "default" and r.port == port for r in registry.records.values()):
                    model_id = await asyncio.to_thread(_match_model_id, settings.models_dir, found["model_path"])
                    record = registry.records['default']
                    record.port = port
                    record.model_id = model_id
                    record.flags = {k: v for k, v in found['flags'].items() if k != 'port'}
                    manager.adopt(pid=found["pid"], model_id=model_id, flags=found["flags"])
    return await manager.status()


async def _launch(req, request, manager, settings, catalog, restart=False):
    registry = request.app.state.instances
    id = request.query_params.get('instance_id', 'default')
    async with registry.lock:
        record, manager = registry.get(id)
        model = await asyncio.to_thread(_find_model, settings, req.model_id)
        if restart and manager.state not in ('running', 'starting'):
            raise HTTPException(409, 'Server is not running; use Start instead')
        if not restart and (manager.state in ('running', 'starting', 'stopping') or manager.restart_pending):
            raise HTTPException(409, 'Server is active; stop it first')
        flags, _ = await asyncio.to_thread(catalog.resolve, req.flags)
        if 'instance_id' in request.query_params:
            flags['port'] = record.port
        elif 'port' not in flags:
            flags['port'] = record.port
        await registry.ensure_port(id, flags, restarting=restart)
        args = await asyncio.to_thread(catalog.build_args, model.entry_path, flags)
        # Persist the requested configuration before spawning or queuing a restart.
        record.model_id = model.id
        record.port = int(flags['port'])
        record.flags = {k: v for k, v in flags.items() if k != 'port'}
        registry.save()
        try:
            if restart:
                result = await manager.restart(model_id=model.id, binary=settings.server_bin, args=args, flags=flags)
            else:
                await manager.start(model_id=model.id, binary=settings.server_bin, args=args, flags=flags)
                result = 'applied'
        except FileNotFoundError:
            raise _binary_not_found(settings)
        status = await manager.status()
        return RestartResponse(result=result, status=status) if restart else status


@router.post('/start', response_model=StatusResponse)
async def start_server(req: StartRequest, request: Request, manager: ManagerDep, settings: SettingsDep, catalog: CatalogDep):
    return await _launch(req, request, manager, settings, catalog)


@router.post('/stop', response_model=StatusResponse)
async def stop_server(request: Request, manager: ManagerDep):
    registry = request.app.state.instances
    async with registry.lock:
        await manager.cancel_restart()
        await manager.stop()
        registry.checkpoint(request.query_params.get('instance_id', 'default'))
        return await manager.status()


@router.post('/restart', response_model=RestartResponse)
async def restart_server(req: StartRequest, request: Request, manager: ManagerDep, settings: SettingsDep, catalog: CatalogDep):
    return await _launch(req, request, manager, settings, catalog, restart=True)


@router.post("/restart/cancel", response_model=StatusResponse)
async def cancel_restart(request: Request, manager: ManagerDep) -> StatusResponse:
    async with request.app.state.instances.lock:
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
