from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.routers import models, presets, server

app = FastAPI(title="LlamaPanel", version=__version__)

app.include_router(models.router)
app.include_router(server.router)
app.include_router(presets.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


# Serve the pre-built frontend (frontend/dist) as static files, so the whole
# app is one process on one port. Mounted last so it never shadows /api/*.
# Release zips ship dist/ pre-built; a git checkout has to run `npm run build`
# first. In `npm run dev`, Vite serves the frontend itself and proxies /api
# here, so the mount is irrelevant there.
_frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if (_frontend_dist / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
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
