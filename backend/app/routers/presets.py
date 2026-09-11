from fastapi import APIRouter, HTTPException

from app import presets as presets_store
from app.schemas import Preset

router = APIRouter(prefix="/api/presets", tags=["presets"])


@router.get("", response_model=list[Preset])
def list_presets() -> list[dict]:
    return presets_store.list_presets()


@router.put("/{name}", response_model=Preset)
def save_preset(name: str, preset: Preset) -> dict:
    if preset.name != name:
        raise HTTPException(status_code=400, detail="Preset name in body must match URL")
    return presets_store.upsert_preset(name, preset.model_id, preset.flags)


@router.delete("/{name}")
def delete_preset(name: str) -> dict:
    if not presets_store.delete_preset(name):
        raise HTTPException(status_code=404, detail=f"Preset '{name}' not found")
    return {"deleted": name}
