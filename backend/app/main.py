from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routers import models, presets, server

app = FastAPI(title="llamaHandler")

app.include_router(models.router)
app.include_router(server.router)
app.include_router(presets.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# Serve the pre-built frontend (frontend/dist) as static files, so the whole
# app is one process on one port. Mounted last so it never shadows /api/*.
# In `npm run dev`, Vite serves the frontend instead and proxies /api here -
# this mount is simply absent if dist/ hasn't been built yet.
_frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
