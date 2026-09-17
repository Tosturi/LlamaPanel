from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.flags import FlagCatalog
from app.introspection import BinaryInspector
from app.llama_client import LlamaClient
from app.presets import PresetStore
from app.process_manager import ProcessManager
from app.routers import models, presets, server
from app.schemas import HealthResponse
from app.settings import Settings


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    """Application factory. Everything with state or side effects (data
    dir, llama-server client, process manager) is created inside lifespan
    and lives on app.state; routers reach it through app.deps. Passing an
    explicit Settings is how run.py and the tests configure the app -
    the environment is only consulted when none is given (uvicorn --reload
    imports "app.main:create_app" by string and can't pass one)."""
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.ensure_dirs()
        client = LlamaClient()
        app.state.settings = settings
        # Lazy: the binary is probed on the first request that needs the
        # flag schema, not here, so a missing llama-server never blocks
        # panel startup (the bundled --help snapshot stands in).
        app.state.inspector = BinaryInspector(settings.server_bin)
        app.state.catalog = FlagCatalog(app.state.inspector)
        app.state.presets = PresetStore(settings.presets_file, resolve=app.state.catalog.resolve)
        # First start after moving data_dir out of the install tree: pick up
        # presets an older release wrote next to run.py instead of showing
        # an empty list. No-op once data_dir has its own presets.json.
        app.state.presets.adopt_legacy_file(settings.legacy_presets_files)
        app.state.manager = ProcessManager(settings, client)
        try:
            yield
        finally:
            await app.state.manager.shutdown()
            await client.aclose()

    app = FastAPI(title="LlamaPanel", version=__version__, lifespan=lifespan)

    app.include_router(models.router)
    app.include_router(server.router)
    app.include_router(presets.router)

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    # Serve the pre-built frontend as static files, so the whole app is one
    # process on one port. Mounted last so it never shadows /api/*. Release
    # zips ship dist/ pre-built; a git checkout has to run `npm run build`
    # first. In `npm run dev`, Vite serves the frontend itself and proxies
    # /api here, so the mount is irrelevant there.
    if (settings.frontend_dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(settings.frontend_dist), html=True), name="frontend")
    else:
        @app.get("/", include_in_schema=False)
        def frontend_missing() -> PlainTextResponse:
            return PlainTextResponse(
                "LlamaPanel API is running, but the web UI is not built.\n\n"
                "Either download a release zip (it ships with the UI pre-built), or from a\n"
                "git checkout run:  cd frontend && npm ci && npm run build\n"
                "then restart run.py.\n",
                status_code=503,
            )

    return app
