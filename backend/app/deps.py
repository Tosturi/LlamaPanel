"""FastAPI dependencies that hand routers the per-app singletons created in
main.lifespan(). Routers never import a global instance - they declare
what they need and get it from app.state, so tests can build an app around
a throwaway Settings/ProcessManager without monkeypatching modules.

HTTPConnection is the common base of Request and WebSocket, so the same
dependency works for both /api/... routes and the /logs websocket.
"""

from typing import Annotated

from fastapi import Depends
from starlette.requests import HTTPConnection

from app.flags import FlagCatalog
from app.introspection import BinaryInspector
from app.presets import PresetStore
from app.process_manager import ProcessManager
from app.settings import Settings


def get_settings(conn: HTTPConnection) -> Settings:
    return conn.app.state.settings


def get_manager(conn: HTTPConnection, instance_id: str = "default") -> ProcessManager:
    return conn.app.state.instances.get(instance_id)[1]


def get_presets(conn: HTTPConnection, instance_id: str = "default") -> PresetStore:
    catalog = get_catalog(conn, instance_id)
    if catalog is conn.app.state.catalog:
        return conn.app.state.presets
    store = PresetStore(conn.app.state.settings.presets_file, resolve=catalog.resolve)
    # All runtimes share the same document lock and atomic storage.
    store._store = conn.app.state.presets._store
    return store


def runtime_services(conn: HTTPConnection, instance_id: str = "default"):
    state = conn.app.state
    record, _ = state.instances.get(instance_id)
    binary = state.instances.runtime_binary(record.runtime_id)
    if record.runtime_id == "default":
        return state.inspector, state.catalog
    cached = state.runtime_services.get(record.runtime_id)
    if cached is None or cached[0].server_bin != binary:
        inspector = BinaryInspector(binary)
        cached = (inspector, FlagCatalog(inspector))
        state.runtime_services[record.runtime_id] = cached
    return cached


def get_inspector(conn: HTTPConnection, instance_id: str = "default") -> BinaryInspector:
    return runtime_services(conn, instance_id)[0]


def get_catalog(conn: HTTPConnection, instance_id: str = "default") -> FlagCatalog:
    return runtime_services(conn, instance_id)[1]


SettingsDep = Annotated[Settings, Depends(get_settings)]
InspectorDep = Annotated[BinaryInspector, Depends(get_inspector)]
CatalogDep = Annotated[FlagCatalog, Depends(get_catalog)]
ManagerDep = Annotated[ProcessManager, Depends(get_manager)]
PresetsDep = Annotated[PresetStore, Depends(get_presets)]
