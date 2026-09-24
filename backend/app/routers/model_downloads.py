from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
import httpx

from app.schemas import ResponseModel

router = APIRouter(prefix='/api/model-downloads', tags=['model downloads'])


class DownloadFile(ResponseModel):
    path: str
    size: int
    sha256: str


class DownloadChoice(ResponseModel):
    name: str
    files: list[DownloadFile]
    size: int


class DownloadPlan(ResponseModel):
    id: str
    repository: str
    revision: str
    choices: list[DownloadChoice]
    projectors: list[DownloadChoice] = []


class DownloadStatus(ResponseModel):
    id: str
    phase: Literal['idle', 'downloading', 'complete', 'cancelled', 'failed']
    name: str
    directory: str
    downloaded: int
    total: int
    message: str


class ResolveRequest(BaseModel):
    source: str = Field(min_length=3, max_length=256)


class DownloadRequest(BaseModel):
    plan_id: str
    choice: int = Field(ge=0)
    projector: int | None = Field(default=None, ge=0)


def guard(request):
    if (origin := request.headers.get('origin')) and urlsplit(origin).netloc != request.headers.get('host'):
        raise HTTPException(403, 'Same-origin request required')


@router.get('', response_model=DownloadStatus)
async def status(request: Request):
    return request.app.state.model_downloads.state


@router.post('/resolve', response_model=DownloadPlan)
async def resolve(body: ResolveRequest, request: Request):
    guard(request)
    try:
        return await request.app.state.model_downloads.resolve(body.source)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except httpx.HTTPError:
        raise HTTPException(502, 'Could not reach Hugging Face. Try again.')


@router.post('', response_model=DownloadStatus, status_code=202)
async def start(body: DownloadRequest, request: Request):
    guard(request)
    if request.app.state.updates.phase in ('downloading', 'preparing', 'restarting'):
        raise HTTPException(409, 'Wait for the application update to finish.')
    service = request.app.state.model_downloads
    try:
        service.start(body.plan_id, body.choice, request.app.state.settings.models_dir, body.projector)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return service.state


@router.post('/cancel', response_model=DownloadStatus)
async def cancel(request: Request):
    guard(request)
    await request.app.state.model_downloads.cancel()
    return request.app.state.model_downloads.state
