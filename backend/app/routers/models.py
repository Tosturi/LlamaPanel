from fastapi import APIRouter

from app.deps import SettingsDep
from app.gguf_scanner import scan, scan_loras
from app.schemas import LoraInfo, ModelInfo

router = APIRouter(tags=["models"])


@router.get("/api/models", response_model=list[ModelInfo])
def list_models(settings: SettingsDep) -> list[ModelInfo]:
    return scan(settings.models_dir)


@router.get("/api/loras", response_model=list[LoraInfo])
def list_loras(settings: SettingsDep) -> list[LoraInfo]:
    """LoRA adapters found in the models directory and its loras/ subfolder."""
    return scan_loras(settings.models_dir, settings.loras_dir)
