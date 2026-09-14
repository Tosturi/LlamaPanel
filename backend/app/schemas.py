from typing import Literal, Optional, Union
from pydantic import BaseModel


class ModelPart(BaseModel):
    filename: str
    path: str
    size_bytes: int


class ModelInfo(BaseModel):
    id: str  # stable id: base name (without split suffix)
    display_name: str
    entry_path: str  # path to pass to llama-server (first part, or the file itself)
    parts: list[ModelPart]
    total_size_bytes: int
    architecture: Optional[str] = None
    file_type: Optional[str] = None
    context_length: Optional[int] = None
    is_split: bool = False


FlagType = Literal["boolean", "number", "string", "enum", "path"]
FlagValue = Union[bool, int, float, str, None]


class FlagDef(BaseModel):
    key: str
    cli: str
    type: FlagType
    label: str
    group: Literal["basic", "advanced"]
    default: Optional[FlagValue] = None
    options: Optional[list[str]] = None
    help: Optional[str] = None


class StartRequest(BaseModel):
    model_id: str
    flags: dict[str, FlagValue] = {}


class Preset(BaseModel):
    name: str
    model_id: str
    flags: dict[str, FlagValue] = {}


ServerState = Literal["stopped", "starting", "running", "stopping", "crashed"]


class StatusResponse(BaseModel):
    state: ServerState
    pid: Optional[int] = None
    model_id: Optional[str] = None
    args: Optional[list[str]] = None
    flags: Optional[dict[str, FlagValue]] = None
    adopted: bool = False
    started_at: Optional[float] = None
    exit_code: Optional[int] = None
    busy: Optional[bool] = None  # None = unknown (server unreachable or started with --no-slots)
    restart_pending: bool = False


class RestartResponse(BaseModel):
    result: Literal["applied", "queued"]
    status: StatusResponse
