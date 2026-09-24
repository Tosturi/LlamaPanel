import asyncio
from fastapi import APIRouter, Request
from app.instances import InstanceConfig, InstanceView
from app.schemas import DeletedResponse, BinaryInfo, FlagDef, ResponseModel
from pydantic import BaseModel
from app.deps import runtime_services
from app.introspection import BinaryInspector
from app.flags import FlagCatalog

router = APIRouter(prefix='/api/instances', tags=['instances'])


@router.get('', response_model=list[InstanceView])
async def list_instances(request: Request):
    registry = request.app.state.instances
    # Migrate a server left running by the former single-instance panel.
    from app.routers.server import get_status
    await get_status(request, registry.managers['default'], registry.settings, runtime_services(request, 'default')[1])
    async with registry.lock:
        return await asyncio.gather(*(registry.view(id) for id in registry.records))


@router.post('', response_model=InstanceView, status_code=201)
async def create_instance(config: InstanceConfig, request: Request):
    registry = request.app.state.instances
    async with registry.lock:
        record = registry.create(config)
        return await registry.view(record.id)


@router.put('/{id}', response_model=InstanceView)
async def update_instance(id: str, config: InstanceConfig, request: Request):
    registry = request.app.state.instances
    async with registry.lock:
        registry.update(id, config)
        return await registry.view(id)


@router.delete('/{id}', response_model=DeletedResponse)
async def delete_instance(id: str, request: Request):
    registry = request.app.state.instances
    async with registry.lock:
        await registry.delete(id)
        return DeletedResponse(deleted=id)


class RuntimeSelection(BaseModel):
    runtime_id: str


class RuntimeView(ResponseModel):
    runtime_id: str
    binary: BinaryInfo
    flags: list[FlagDef]


@router.get('/{id}/runtime', response_model=RuntimeView)
async def get_runtime(id: str, request: Request):
    registry = request.app.state.instances
    async with registry.lock:
        record, _ = registry.get(id)
        inspector, catalog = runtime_services(request, id)
        binary = await asyncio.to_thread(inspector.inspect)
        return RuntimeView(runtime_id=record.runtime_id, binary=binary,
                           flags=await asyncio.to_thread(catalog.schema))


@router.put('/{id}/runtime', response_model=RuntimeView)
async def select_runtime(id: str, selection: RuntimeSelection, request: Request):
    state = request.app.state
    registry = state.instances
    async with registry.lock:
        record, _ = registry.get(id)
        executable = registry.runtime_binary(selection.runtime_id)
        inspector = BinaryInspector(executable)
        binary = await asyncio.to_thread(inspector.inspect)
        catalog = FlagCatalog(inspector)
        flags = await asyncio.to_thread(catalog.schema)
        previous = record.runtime_id
        record.runtime_id = selection.runtime_id
        try:
            registry.save()
        except Exception:
            record.runtime_id = previous
            raise
        if selection.runtime_id == "default":
            state.inspector, state.catalog = inspector, catalog
            state.presets._resolve = catalog.resolve
        else:
            state.runtime_services[selection.runtime_id] = inspector, catalog
        return RuntimeView(runtime_id=record.runtime_id, binary=binary, flags=flags)
