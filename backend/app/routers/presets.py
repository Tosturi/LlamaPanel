from fastapi import APIRouter, HTTPException

from app.deps import PresetsDep
from app.schemas import DeletedResponse, Preset
from app.storage import NewerFormatError

router = APIRouter(prefix="/api/presets", tags=["presets"])


def _newer_format(exc: NewerFormatError) -> HTTPException:
    # The file was written by a newer LlamaPanel; refusing (instead of
    # overwriting) is deliberate, so tell the user exactly what to do.
    return HTTPException(status_code=500, detail=str(exc))


@router.get("", response_model=list[Preset])
def list_presets(store: PresetsDep) -> list[dict]:
    try:
        return store.list()
    except NewerFormatError as exc:
        raise _newer_format(exc)


@router.put("/{name}", response_model=Preset)
def save_preset(name: str, preset: Preset, store: PresetsDep) -> dict:
    if preset.name != name:
        raise HTTPException(status_code=400, detail="Preset name in body must match URL")
    try:
        return store.upsert(name, preset.model_id, preset.flags)
    except NewerFormatError as exc:
        raise _newer_format(exc)


@router.delete("/{name}", response_model=DeletedResponse)
def delete_preset(name: str, store: PresetsDep) -> DeletedResponse:
    try:
        deleted = store.delete(name)
    except NewerFormatError as exc:
        raise _newer_format(exc)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Preset '{name}' not found")
    return DeletedResponse(deleted=name)
