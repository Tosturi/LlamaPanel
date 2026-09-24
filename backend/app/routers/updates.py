import ipaddress
import os
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app import __version__
from app.schemas import ResponseModel

router = APIRouter(prefix='/api/updates', tags=['updates'])


class UpdateStatus(ResponseModel):
    current_version: str
    latest_version: str | None
    notes: str
    phase: Literal['idle', 'downloading', 'preparing', 'restarting', 'complete', 'failed']
    message: str
    supported: bool
    reason: str | None
    available: bool


class InstallRequest(BaseModel):
    version: str


def local(request):
    try:
        host = request.url.hostname
        host_local = host == 'localhost' or ipaddress.ip_address(host or '').is_loopback
        return host_local and request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        return False


def status(request):
    result = request.app.state.updates.status()
    if result['supported'] and not local(request):
        result.update(supported=False, reason='Open the panel on localhost to install updates.')
    return result


@router.get('', response_model=UpdateStatus)
def get_status(request: Request):
    return status(request)


@router.post('/check', response_model=UpdateStatus)
async def check(request: Request):
    try:
        await request.app.state.updates.check()
    except Exception as exc:
        raise HTTPException(502, f'Could not check for updates: {exc}')
    return status(request)


@router.post('/install', response_model=UpdateStatus, status_code=202)
async def install(body: InstallRequest, request: Request):
    if not local(request):
        raise HTTPException(403, 'Updates can only be installed from localhost')
    if (origin := request.headers.get('origin')) and urlsplit(origin).netloc != request.headers.get('host'):
        raise HTTPException(403, 'Same-origin request required')
    if request.app.state.native_picker_lock.locked():
        raise HTTPException(409, 'Close the file picker before updating')
    if request.app.state.model_downloads.busy:
        raise HTTPException(409, 'Finish or cancel the model download before updating')
    try:
        request.app.state.updates.start(body.version)
    except (ValueError, OSError) as exc:
        raise HTTPException(409, str(exc))
    return status(request)


@router.get('/ready', include_in_schema=False)
def ready():
    return {'token': os.environ.get('LLAMAPANEL_LAUNCH_TOKEN', ''), 'version': __version__}
