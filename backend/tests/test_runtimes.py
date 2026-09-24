import dataclasses
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings, RuntimeConfig
from tests.test_app_settings import payload


def configure(client, tmp_path):
    values = payload(tmp_path)
    values['runtimes'] = [{'id': 'fork', 'name': 'Experimental', 'server_bin': sys.executable}]
    result = client.put('/api/settings', json=values)
    assert result.status_code == 200, result.text
    return values


def test_settings_persistence_and_used_runtime_guard(client, tmp_path, settings):
    values = configure(client, tmp_path)
    saved = Settings.load({'data_dir': settings.data_dir})
    assert saved.runtimes[0].name == 'Experimental'
    assert saved.runtimes[0].server_bin == str(Path(sys.executable).resolve())
    response = client.put('/api/instances/default/runtime', json={'runtime_id': 'fork'})
    assert response.status_code == 200, response.text
    assert response.json()['binary']['server_bin'] == saved.runtimes[0].server_bin
    # Old clients saving other configuration must preserve the selection.
    result = client.put('/api/instances/default', json={'name': 'Local', 'port': 8080})
    assert result.json()['runtime_id'] == 'fork'
    values['runtimes'] = []
    assert client.put('/api/settings', json=values).status_code == 409
    assert client.put('/api/instances/default/runtime', json={'runtime_id': 'missing'}).status_code == 422
    assert client.get('/api/instances/default/runtime').json()['runtime_id'] == 'fork'
    with TestClient(create_app(saved)) as restarted:
        assert restarted.get('/api/instances/default/runtime').json()['runtime_id'] == 'fork'
    assert client.put('/api/instances/default/runtime', json={'runtime_id': 'default'}).status_code == 200
    assert client.put('/api/settings', json=values).status_code == 200


@pytest.mark.parametrize('runtimes', [
    [{'id': 'default', 'name': 'Reserved', 'server_bin': sys.executable}],
    [{'id': 'fork', 'name': ' ', 'server_bin': sys.executable}],
    [{'id': 'fork', 'name': 'Broken', 'server_bin': '/not/a/binary'}],
    [{'id': 'fork', 'name': 'One', 'server_bin': sys.executable},
     {'id': 'fork', 'name': 'Two', 'server_bin': sys.executable}],
])
def test_invalid_runtime_settings(client, tmp_path, runtimes):
    values = payload(tmp_path)
    values['runtimes'] = runtimes
    assert client.put('/api/settings', json=values).status_code == 422
    assert client.get('/api/settings').json()['runtimes'] == []


def test_selection_probes_again_and_isolates_schema_launch_and_presets(settings, tmp_path, monkeypatch):
    settings = dataclasses.replace(settings, server_bin='main-bin',
                                  runtimes=(RuntimeConfig(id='fork', name='Fork', server_bin='fork-bin'),))
    calls = []
    monkeypatch.setattr('app.introspection.resolve_binary', lambda value: Path(value))
    def run(binary, option):
        calls.append((str(binary), option))
        if option == '--version':
            return 'version: 1234 (abcdef)'
        key = 'experimental' if str(binary) == 'fork-bin' else 'main-only'
        return f'----- common params -----\n--{key} N  custom option (default: 1)\n--port N  server port (default: 8080)\n'
    monkeypatch.setattr('app.introspection._run', run)
    monkeypatch.setattr('app.discovery.find_running_llama_server', lambda *args: None)
    settings.models_dir.mkdir()
    (settings.models_dir / 'model.gguf').write_bytes(b'GGUF')
    with TestClient(create_app(settings)) as client:
        second = client.post('/api/instances', json={'name': 'Second', 'port': 8081}).json()['id']
        route = f'/api/instances/{second}/runtime'
        selected = client.put(route, json={'runtime_id': 'fork'}).json()
        assert any(f['key'] == 'experimental' for f in selected['flags'])
        assert client.get('/api/server/binary').json()['server_bin'] == 'main-bin'
        assert client.get(f'/api/server/binary?instance_id={second}').json()['server_bin'] == 'fork-bin'
        count = calls.count(('fork-bin', '--help'))
        client.get(route)
        assert calls.count(('fork-bin', '--help')) == count
        client.put(route, json={'runtime_id': 'default'})
        client.put(route, json={'runtime_id': 'fork'})
        assert calls.count(('fork-bin', '--help')) == count + 1
        assert client.put(f'/api/presets/test?instance_id={second}', json={
            'name': 'test', 'model_id': 'model', 'flags': {'experimental': 7}}).status_code == 200
        assert client.get('/api/presets').json()[0]['unsupported'] == ['experimental']
        assert client.get(f'/api/presets?instance_id={second}').json()[0]['unsupported'] == []
        registry = client.app.state.instances
        launches = []
        async def start(**kwargs):
            launches.append(kwargs)
        async def ensure(*args, **kwargs):
            pass
        monkeypatch.setattr(registry.managers[second], 'start', start)
        monkeypatch.setattr(registry, 'ensure_port', ensure)
        result = client.post(f'/api/server/start?instance_id={second}',
                             json={'model_id': 'model', 'flags': {'experimental': 7}})
        assert result.status_code == 200, result.text
        assert launches[0]['binary'] == 'fork-bin'
        assert '--experimental' in launches[0]['args']
        assert registry.records['default'].runtime_id == 'default'
        # Selection never starts/stops a process by itself.
        client.put(route, json={'runtime_id': 'default'})
        assert len(launches) == 1
