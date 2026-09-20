import asyncio
import dataclasses
import socket
import sys

import psutil
import pytest
from fastapi.testclient import TestClient

from app.instances import InstanceConfig, InstanceRegistry
from app.main import create_app
from app.process_manager import ProcessManager
from tests.fakes import FakeLlamaClient


def test_crud_and_persistence(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get('/api/instances').json()[0]['id'] == 'default'
        resp = client.post('/api/instances', json={'name': 'Embeddings', 'port': 18081})
        assert resp.status_code == 201
        id = resp.json()['id']
        resp = client.put(f'/api/instances/{id}', json={
            'name': 'Embed', 'port': 18082, 'model_id': 'm', 'flags': {'ctx_size': 4096, 'port': 8080}})
        assert resp.status_code == 200
        assert resp.json()['flags'] == {'ctx_size': 4096}
        assert client.post('/api/instances', json={'name': 'Conflict', 'port': 18082}).status_code == 409
        assert client.post('/api/instances', json={'name': ' ', 'port': 18083}).status_code == 422
        assert client.delete('/api/instances/default').status_code == 409
        assert client.get('/api/server/status?instance_id=missing').status_code == 404
    with TestClient(create_app(settings)) as client:
        rows = client.get('/api/instances').json()
        assert rows[1]['name'] == 'Embed'
        assert rows[1]['model_id'] == 'm'
        assert rows[1]['port'] == 18082
        assert client.delete(f'/api/instances/{id}').status_code == 200
        assert len(client.get('/api/instances').json()) == 1


def test_scoped_start_and_stop_and_port_conflict(client, settings, monkeypatch):
    settings.models_dir.mkdir()
    (settings.models_dir / 'm.gguf').write_bytes(b'')
    async def start(self, model_id, binary, args, flags):
        self._state = 'starting'
        self._model_id, self._args, self._flags = model_id, args, flags
    async def stop(self):
        self._state = 'stopped'
    monkeypatch.setattr(ProcessManager, 'start', start)
    monkeypatch.setattr(ProcessManager, 'stop', stop)
    id = client.post('/api/instances', json={'name': 'Second', 'port': 18091}).json()['id']
    resp = client.post(f'/api/server/start?instance_id={id}', json={'model_id': 'm', 'flags': {'port': 8080, 'ctx_size': 64000}})
    assert resp.status_code == 200
    assert resp.json()['flags'] == {'port': 18091, 'ctx_size': 64000}
    assert client.post('/api/server/start', json={'model_id': 'm', 'flags': {'port': 18091}}).status_code == 409
    assert client.put(f'/api/instances/{id}', json={'name': 'Second', 'port': 18092}).status_code == 409
    assert client.delete(f'/api/instances/{id}').status_code == 409
    client.post('/api/server/stop')
    assert client.get(f'/api/server/status?instance_id={id}').json()['state'] == 'starting'
    client.post(f'/api/server/stop?instance_id={id}')
    assert client.delete(f'/api/instances/{id}').status_code == 200


def test_occupied_external_port_rejected(client, settings):
    settings.models_dir.mkdir()
    (settings.models_dir / 'm.gguf').write_bytes(b'')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        sock.listen()
        port = sock.getsockname()[1]
        id = client.post('/api/instances', json={'name': 'Busy', 'port': port}).json()['id']
        assert client.post(f'/api/server/start?instance_id={id}', json={'model_id': 'm'}).status_code == 409


def test_scoped_log_streams_do_not_leak(client):
    id = client.post('/api/instances', json={'name': 'Second', 'port': 18101}).json()['id']
    registry = client.app.state.instances
    registry.managers['default']._emit('first-only')
    registry.managers[id]._emit('second-only')
    with client.websocket_connect('/api/server/logs?instance_id=default') as ws:
        assert ws.receive_text() == 'first-only'
    with client.websocket_connect(f'/api/server/logs?instance_id={id}') as ws:
        assert ws.receive_text() == 'second-only'


async def test_real_parallel_children_restore_and_independent_stop(settings, tmp_path):
    # Actual subprocesses, without model/GPU dependencies. Fake health only.
    settings = dataclasses.replace(settings, server_bin=sys.executable)
    registry = InstanceRegistry(settings, FakeLlamaClient(healthy=[True], busy=[False]))
    second = registry.create(InstanceConfig(name='Second', port=18111))
    first_manager = registry.managers['default']
    second_manager = registry.managers[second.id]
    script = tmp_path / 'worker.py'
    script.write_text('import time,sys\nprint(sys.argv[1], flush=True)\ntime.sleep(60)\n')
    restored = None
    try:
        await asyncio.gather(
            first_manager.start('first', sys.executable, [str(script), 'FIRST'], {'port': 8080}),
            second_manager.start('second', sys.executable, [str(script), 'SECOND'], {'port': 18111}),
        )
        assert first_manager._pid != second_manager._pid
        for _ in range(100):
            if 'FIRST' in first_manager._log_buffer and 'SECOND' in second_manager._log_buffer:
                break
            await asyncio.sleep(.02)
        assert 'FIRST' in first_manager._log_buffer
        assert 'SECOND' not in first_manager._log_buffer
        assert 'SECOND' in second_manager._log_buffer
        await registry.shutdown()
        assert psutil.pid_exists(first_manager._pid) and psutil.pid_exists(second_manager._pid)
        restored = InstanceRegistry(settings, FakeLlamaClient(healthy=[True], busy=[False]))
        assert restored.managers['default']._adopted
        assert restored.managers[second.id]._adopted
        assert restored.managers[second.id]._pid == second_manager._pid
        await restored.managers['default'].stop(timeout=.1)
        assert psutil.Process(second_manager._pid).is_running()
        await restored.managers[second.id].stop(timeout=.1)
    finally:
        for manager in (first_manager, second_manager):
            if manager._proc and manager._proc.returncode is None:
                try: manager._proc.kill()
                except ProcessLookupError: pass
                await manager._proc.wait()
        if restored:
            await restored.shutdown()
        await registry.shutdown()


async def test_reused_pid_is_not_adopted(settings):
    registry = InstanceRegistry(settings, FakeLlamaClient())
    record = registry.records['default']
    record.pid = psutil.Process().pid
    record.created_at = psutil.Process().create_time() - 100
    registry.save()
    restored = InstanceRegistry(settings, FakeLlamaClient())
    assert restored.managers['default'].state == 'stopped'
    await restored.shutdown()
    await registry.shutdown()


def test_queued_restarts_and_cancellation_are_per_instance(client, settings, monkeypatch):
    settings.models_dir.mkdir()
    (settings.models_dir / 'm.gguf').write_bytes(b'')
    registry = client.app.state.instances
    id = client.post('/api/instances', json={'name': 'Second', 'port': 18121}).json()['id']
    for key in ('default', id):
        manager = registry.managers[key]
        manager._state = 'running'
        manager._flags = {'port': registry.records[key].port}
        manager._client = FakeLlamaClient(busy=[True])
    for key in ('default', id):
        response = client.post(f'/api/server/restart?instance_id={key}', json={'model_id': 'm', 'flags': {'ctx_size': 8192}})
        assert response.status_code == 200
        assert response.json()['result'] == 'queued'
    client.post('/api/server/restart/cancel?instance_id=default')
    assert not registry.managers['default'].restart_pending
    assert registry.managers[id].restart_pending
    # A requested port is reserved even while the old process is busy.
    assert client.post('/api/instances', json={'name': 'Conflict', 'port': 18121}).status_code == 409


def test_legacy_discovery_does_not_adopt_another_instance(client, monkeypatch):
    id = client.post('/api/instances', json={'name': 'Second', 'port': 18131}).json()['id']
    manager = client.app.state.instances.managers[id]
    manager._pid = 12345
    monkeypatch.setattr('app.routers.server.discovery.find_running_llama_server', lambda *args: {
        'pid': 12345, 'model_path': None, 'flags': {'port': 18131}})
    assert client.get('/api/server/status').json()['state'] == 'stopped'
    assert client.app.state.instances.managers['default']._pid is None
