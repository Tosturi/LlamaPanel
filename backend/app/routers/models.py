from fastapi import APIRouter

from app import config
from app.gguf_scanner import scan
from app.schemas import ModelInfo

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("", response_model=list[ModelInfo])
def list_models() -> list[ModelInfo]:
    return scan(config.MODELS_DIR)
