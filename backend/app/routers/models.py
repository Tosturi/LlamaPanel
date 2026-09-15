from fastapi import APIRouter

from app.deps import SettingsDep
from app.gguf_scanner import scan
from app.schemas import ModelInfo

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("", response_model=list[ModelInfo])
def list_models(settings: SettingsDep) -> list[ModelInfo]:
    return scan(settings.models_dir)
