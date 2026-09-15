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

from app.presets import PresetStore
from app.process_manager import ProcessManager
from app.settings import Settings


def get_settings(conn: HTTPConnection) -> Settings:
    return conn.app.state.settings


def get_manager(conn: HTTPConnection) -> ProcessManager:
    return conn.app.state.manager


def get_presets(conn: HTTPConnection) -> PresetStore:
    return conn.app.state.presets


SettingsDep = Annotated[Settings, Depends(get_settings)]
ManagerDep = Annotated[ProcessManager, Depends(get_manager)]
PresetsDep = Annotated[PresetStore, Depends(get_presets)]
