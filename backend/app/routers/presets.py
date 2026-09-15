from fastapi import APIRouter, HTTPException

from app.deps import PresetsDep
from app.schemas import DeletedResponse, Preset

router = APIRouter(prefix="/api/presets", tags=["presets"])


@router.get("", response_model=list[Preset])
def list_presets(store: PresetsDep) -> list[dict]:
    return store.list()


@router.put("/{name}", response_model=Preset)
def save_preset(name: str, preset: Preset, store: PresetsDep) -> dict:
    if preset.name != name:
        raise HTTPException(status_code=400, detail="Preset name in body must match URL")
    return store.upsert(name, preset.model_id, preset.flags)


@router.delete("/{name}", response_model=DeletedResponse)
def delete_preset(name: str, store: PresetsDep) -> DeletedResponse:
    if not store.delete(name):
        raise HTTPException(status_code=404, detail=f"Preset '{name}' not found")
    return DeletedResponse(deleted=name)
