import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings

from tests.fakes import FakeLlamaClient


@pytest.fixture
def settings(tmp_path) -> Settings:
    """A Settings pointed entirely at tmp_path, so tests never touch the
    real models/ or data/ directories and never read the environment."""
    return Settings(
        models_dir=tmp_path / "models",
        data_dir=tmp_path / "data",
        server_bin="llama-server",
        frontend_dist=tmp_path / "no-dist",
        legacy_data_dirs=(),
    )


@pytest.fixture(autouse=True)
def no_real_binary(monkeypatch):
    """Never probe a llama-server that happens to be installed on the dev
    machine: the flag schema then always comes from the bundled snapshot,
    so tests are deterministic. Tests that exercise probing patch
    resolve_binary/_run themselves on top of this."""
    monkeypatch.setattr("app.introspection.resolve_binary", lambda server_bin: None)


@pytest.fixture
def client(settings):
    """TestClient with the lifespan running, i.e. app.state populated the
    same way it is in production."""
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def fake_llama():
    return FakeLlamaClient()
