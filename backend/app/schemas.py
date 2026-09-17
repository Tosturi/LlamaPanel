from typing import Literal, Optional, Union
from pydantic import BaseModel, ConfigDict


class ResponseModel(BaseModel):
    """Base for everything the API returns. FastAPI always serializes every
    field of a response model (defaults included), so in the OpenAPI schema
    those fields are marked required. Without this, `Optional[x] = None`
    fields would come out as `x?: ...` in the generated TypeScript types
    and every consumer would need a `?? null`."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class ModelPart(ResponseModel):
    filename: str
    path: str
    size_bytes: int


class ModelInfo(ResponseModel):
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


class FlagDef(ResponseModel):
    key: str
    cli: str
    type: FlagType
    label: str
    group: Literal["basic", "advanced"]
    default: Optional[FlagValue] = None
    options: Optional[list[str]] = None
    help: Optional[str] = None


class LlamaArg(ResponseModel):
    """One option as reported by `llama-server --help`. Type, options and
    default are inferred from the help text (see app/introspection.py)."""

    key: str  # first long spelling, --ctx-size -> ctx_size
    args: list[str]  # every positive spelling, short and long
    args_neg: list[str] = []  # --no-* twins, when the flag has them
    value_hints: list[str] = []  # [] for a bare switch, ["N"], ["FNAME", "SCALE"], ...
    type: FlagType
    options: Optional[list[str]] = None
    default: Optional[FlagValue] = None
    help: str = ""
    env: Optional[str] = None
    section: str = ""  # "common params", "sampling params", ...
    repeatable: bool = False
    deprecated: bool = False  # help says "DEPRECATED" / "has been removed"


class BinaryInfo(ResponseModel):
    """What the panel learned by probing the configured llama-server."""

    server_bin: str
    resolved_path: Optional[str] = None
    build: Optional[int] = None  # llama.cpp build number, e.g. 6789
    commit: Optional[str] = None
    args: list[LlamaArg] = []
    error: Optional[str] = None  # set when the binary is missing or a probe failed


class StartRequest(BaseModel):
    model_id: str
    flags: dict[str, FlagValue] = {}


class Preset(BaseModel):
    name: str
    model_id: str
    flags: dict[str, FlagValue] = {}
    # Unix time of the last save; None for presets migrated from older files.
    # Set by the server, ignored on input.
    updated_at: Optional[float] = None


ServerState = Literal["stopped", "starting", "running", "stopping", "crashed"]


class StatusResponse(ResponseModel):
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


class RestartResponse(ResponseModel):
    result: Literal["applied", "queued"]
    status: StatusResponse


class HealthResponse(ResponseModel):
    status: Literal["ok"]
    version: str


class DeletedResponse(ResponseModel):
    deleted: str
