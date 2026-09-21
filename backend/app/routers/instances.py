import asyncio
from fastapi import APIRouter, Request
from app.instances import InstanceConfig, InstanceView
from app.schemas import DeletedResponse

router = APIRouter(prefix='/api/instances', tags=['instances'])


@router.get('', response_model=list[InstanceView])
async def list_instances(request: Request):
    registry = request.app.state.instances
    # Migrate a server left running by the former single-instance panel.
    from app.routers.server import get_status
    await get_status(request, registry.managers['default'], registry.settings, request.app.state.catalog)
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
