"""Global settings and a read-only browser of the backend machine's paths."""
import asyncio
import dataclasses
import os
from pathlib import Path
import shutil
import string
import ipaddress
from urllib.parse import urlsplit
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.deps import SettingsDep
from app.flags import FlagCatalog
from app.introspection import BinaryInspector
from app.presets import PresetStore
from app.schemas import ResponseModel
from app.settings import settings_store, RuntimeConfig, validate_runtimes
from app.native_picker import pick_path

router = APIRouter(prefix="/api/settings", tags=["settings"])


class NativePickerRequest(BaseModel):
    mode: Literal["directory", "file"]
    initial: str = Field(default="", max_length=4096)


class NativePickerView(ResponseModel):
    available: bool
    path: str | None


@router.post("/pick", response_model=NativePickerView)
async def native_picker(body: NativePickerRequest, request: Request):
    # A remote browser must not open windows on someone else's desktop.
    try:
        local = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        local = False
    if not local:
        return NativePickerView(available=False, path=None)
    origin = request.headers.get('origin')
    if origin and urlsplit(origin).netloc != request.headers.get('host'):
        raise HTTPException(403, 'Native picker requires a same-origin request')
    lock = request.app.state.native_picker_lock
    if lock.locked():
        raise HTTPException(409, 'A file picker is already open')
    async with lock:
        try:
            return NativePickerView(**await pick_path(body.mode, body.initial))
        except (OSError, NotImplementedError):
            return NativePickerView(available=False, path=None)


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    models_dir: str = Field(min_length=1, max_length=4096)
    loras_dir: str = Field(min_length=1, max_length=4096)
    server_bin: str = Field(min_length=1, max_length=4096)
    runtimes: list[RuntimeConfig] = Field(default_factory=list)


class SettingsView(ResponseModel):
    models_dir: str
    loras_dir: str
    server_bin: str
    runtimes: list[RuntimeConfig]
    data_dir: str
    locked_fields: list[str]
    needs_setup: bool


def view(settings):
    return SettingsView(models_dir=str(settings.models_dir),
                        loras_dir=str(settings.loras_dir or settings.models_dir / "loras"),
                        server_bin=settings.server_bin, runtimes=list(settings.runtimes), data_dir=str(settings.data_dir),
                        locked_fields=list(settings.locked_fields),
                        needs_setup=(not settings.models_dir.is_dir()
                                     or not (settings.loras_dir or settings.models_dir / "loras").is_dir()
                                     or not shutil.which(settings.server_bin)))


@router.get("", response_model=SettingsView)
def get_settings(settings: SettingsDep):
    return view(settings)


def validate_paths(update):
    values = update.model_dump()
    for key in ("models_dir", "loras_dir"):
        path = Path(values[key]).expanduser()
        if not path.is_absolute() or not path.is_dir():
            raise HTTPException(422, f"{key}: select an existing absolute directory")
        try:
            with os.scandir(path):
                pass
        except OSError:
            raise HTTPException(422, f"{key}: directory is not readable")
        values[key] = str(path.resolve())
    binary = os.path.expanduser(values["server_bin"])
    resolved = shutil.which(binary)
    if not resolved or not Path(resolved).is_file():
        raise HTTPException(422, "server_bin: executable was not found or is not executable")
    values["server_bin"] = str(Path(resolved).resolve())
    try:
        runtimes = validate_runtimes(values["runtimes"])
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    for runtime in runtimes:
        resolved = shutil.which(os.path.expanduser(runtime.server_bin))
        if not resolved or not Path(resolved).is_file():
            raise HTTPException(422, f"{runtime.name}: executable was not found or is not executable")
        next(r for r in values["runtimes"] if r["id"] == runtime.id)["server_bin"] = str(Path(resolved).resolve())
    return values


@router.put("", response_model=SettingsView)
async def save_settings(update: SettingsUpdate, request: Request):
    state = request.app.state
    async with state.instances.lock:
        current = state.settings
        for key in current.locked_fields:
            if getattr(update, key) != str(getattr(current, key)):
                raise HTTPException(409, f"{key} is overridden by a launch argument or environment variable")
        if "runtimes" not in update.model_fields_set:
            update.runtimes = list(current.runtimes)
        values = await asyncio.to_thread(validate_paths, update)
        ids = {r["id"] for r in values["runtimes"]} | {"default"}
        used = [r.name for r in state.instances.records.values() if r.runtime_id not in ids]
        if used:
            raise HTTPException(409, "Runtime is used by: " + ", ".join(used) + ". Select another runtime first.")
        # Never persist launch-only overrides as user preferences.
        store = settings_store(current.data_dir)
        saved = await asyncio.to_thread(store.load)
        saved.update({k: v for k, v in values.items() if k not in current.locked_fields})
        try:
            await asyncio.to_thread(store.save, saved)
        except OSError as exc:
            raise HTTPException(500, f"Could not save settings: {exc}")
        updated = dataclasses.replace(current, models_dir=Path(values["models_dir"]),
                                      loras_dir=Path(values["loras_dir"]), server_bin=values["server_bin"],
                                      runtimes=validate_runtimes(values["runtimes"]))
        inspector = BinaryInspector(updated.server_bin)
        catalog = FlagCatalog(inspector)
        state.settings = updated
        state.instances.settings = updated
        state.runtime_services.clear()
        state.inspector = inspector
        state.catalog = catalog
        state.presets = PresetStore(updated.presets_file, resolve=catalog.resolve)
        return view(updated)


class BrowserEntry(ResponseModel):
    name: str
    path: str
    directory: bool


class BrowserView(ResponseModel):
    path: str
    parent: str | None
    roots: list[str]
    entries: list[BrowserEntry]


def browser_roots():
    if os.name == "nt":
        return [f"{letter}:\\" for letter in string.ascii_uppercase if Path(f"{letter}:\\").is_dir()]
    return ["/", str(Path.home())]


@router.get("/browse", response_model=BrowserView)
def browse(path: str | None = None, mode: Literal["directory", "file"] = "directory"):
    directory = Path(path).expanduser() if path else Path.home()
    if not directory.is_absolute():
        raise HTTPException(422, "Enter an absolute path on the backend machine")
    try:
        directory = directory.resolve(strict=True)
        entries = []
        with os.scandir(directory) as listing:
            for entry in listing:
                try:
                    is_dir = entry.is_dir()
                    if is_dir or (mode == "file" and entry.is_file()):
                        entries.append(BrowserEntry(name=entry.name, path=str(directory / entry.name), directory=is_dir))
                except OSError:
                    continue
    except PermissionError:
        raise HTTPException(403, "This directory is not accessible to the panel")
    except (OSError, ValueError):
        raise HTTPException(404, "Directory does not exist or is unavailable")
    return BrowserView(path=str(directory), parent=str(directory.parent) if directory.parent != directory else None,
                       roots=browser_roots(), entries=sorted(entries, key=lambda e: (not e.directory, e.name.casefold())))
