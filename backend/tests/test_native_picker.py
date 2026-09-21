import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.native_picker import pick_path


@pytest.mark.parametrize('path', ['/tmp/chosen', None])
def test_local_selection_and_cancel(settings, monkeypatch, path):
    picker = AsyncMock(return_value={'available': True, 'path': path})
    monkeypatch.setattr('app.routers.settings.pick_path', picker)
    with TestClient(create_app(settings), client=('127.0.0.1', 5000)) as client:
        result = client.post('/api/settings/pick', json={'mode':'directory','initial':'/tmp'})
        assert result.json() == {'available': True, 'path':path}
        picker.assert_awaited_once_with('directory','/tmp')
        assert not client.app.state.native_picker_lock.locked()


def test_remote_client_uses_browser(settings, monkeypatch):
    picker = AsyncMock()
    monkeypatch.setattr('app.routers.settings.pick_path', picker)
    with TestClient(create_app(settings), client=('192.0.2.1', 5000)) as client:
        assert client.post('/api/settings/pick', json={'mode':'file'}).json() == {'available':False,'path':None}
    picker.assert_not_awaited()


def test_cross_origin_and_duplicate_requests(settings, monkeypatch):
    picker = AsyncMock()
    monkeypatch.setattr('app.routers.settings.pick_path', picker)
    with TestClient(create_app(settings), client=('127.0.0.1', 5000)) as client:
        assert client.post('/api/settings/pick', json={'mode':'file'}, headers={'origin':'https://other.example'}).status_code == 403
        client.portal.call(client.app.state.native_picker_lock.acquire)
        assert client.post('/api/settings/pick', json={'mode':'file'}).status_code == 409
        client.app.state.native_picker_lock.release()
    picker.assert_not_awaited()


async def test_worker_timeout_terminates_process(monkeypatch):
    class Process:
        returncode = None
        killed = False
        async def communicate(self):
            raise TimeoutError()
        def kill(self):
            self.killed = True
        async def wait(self):
            self.returncode = -9
    process = Process()
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', AsyncMock(return_value=process))
    assert await pick_path('file','/tmp') == {'available':False,'path':None}
    assert process.killed


async def test_worker_request_cancellation_terminates_process(monkeypatch):
    class Process:
        returncode = None
        killed = False
        async def communicate(self):
            raise asyncio.CancelledError()
        def kill(self):
            self.killed = True
        async def wait(self):
            self.returncode = -9
    process = Process()
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', AsyncMock(return_value=process))
    with pytest.raises(asyncio.CancelledError):
        await pick_path('file','/tmp')
    assert process.killed
