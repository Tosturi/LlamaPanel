import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings, settings_store
from app.storage import NewerFormatError


def payload(tmp_path):
    models = tmp_path / 'models new'
    loras = tmp_path / 'adapters new'
    models.mkdir(exist_ok=True)
    loras.mkdir(exist_ok=True)
    return dict(models_dir=str(models), loras_dir=str(loras), server_bin=sys.executable)


def test_save_reload_and_independent_lora_library(client, settings, tmp_path, monkeypatch):
    values = payload(tmp_path)
    Path(values['models_dir'], 'chat.gguf').write_bytes(b'GGUF')
    Path(values['loras_dir'], 'adapter.gguf').write_bytes(b'GGUF')
    manager = client.app.state.manager
    original_log = manager._settings.log_file
    result = client.put('/api/settings', json=values)
    assert result.status_code == 200, result.text
    assert client.app.state.manager is manager
    assert manager._settings.log_file == original_log
    assert [m['id'] for m in client.get('/api/models').json()] == ['chat']
    assert [m['id'] for m in client.get('/api/loras').json()] == ['adapter']
    document = json.loads((settings.data_dir / 'settings.json').read_text())
    assert document['version'] == 1
    assert document['settings']['models_dir'] == values['models_dir']
    monkeypatch.setenv('LLAMAPANEL_DATA_DIR', str(settings.data_dir))
    restarted = Settings.from_env()
    assert restarted.models_dir == Path(values['models_dir'])
    assert restarted.loras_dir == Path(values['loras_dir'])
    assert restarted.server_bin == str(Path(sys.executable).resolve())


@pytest.mark.parametrize('field,value', [('models_dir', 'relative'), ('loras_dir', '/does-not-exist'), ('server_bin', 'no-such-binary-llamapanel')])
def test_invalid_settings_leave_file_and_runtime_unchanged(client, settings, tmp_path, field, value):
    values = payload(tmp_path)
    assert client.put('/api/settings', json=values).status_code == 200
    before = (settings.data_dir / 'settings.json').read_bytes()
    runtime = client.app.state.settings
    values[field] = value
    assert client.put('/api/settings', json=values).status_code == 422
    assert (settings.data_dir / 'settings.json').read_bytes() == before
    assert client.app.state.settings is runtime


def test_failed_write_does_not_apply_runtime_settings(client, tmp_path, monkeypatch):
    from app.storage import JsonDocumentStore
    current = client.app.state.settings
    def fail(*args):
        raise PermissionError('read-only')
    monkeypatch.setattr(JsonDocumentStore, 'save', fail)
    assert client.put('/api/settings', json=payload(tmp_path)).status_code == 500
    assert client.app.state.settings is current
    monkeypatch.undo()  # allow instance shutdown to checkpoint


def test_launch_overrides_are_locked_and_not_persisted(settings, tmp_path, monkeypatch):
    values = payload(tmp_path)
    monkeypatch.setenv('LLAMAPANEL_DATA_DIR', str(settings.data_dir))
    settings_store(settings.data_dir).save(values)
    monkeypatch.setenv('LLAMAPANEL_MODELS_DIR', str(tmp_path))
    loaded = Settings.load({'models_dir': values['models_dir']})
    assert loaded.models_dir == Path(values['models_dir'])
    assert 'models_dir' in loaded.locked_fields
    with TestClient(create_app(loaded)) as client:
        changed = {**values, 'models_dir': str(tmp_path)}
        assert client.put('/api/settings', json=changed).status_code == 409
        assert client.put('/api/settings', json=values).status_code == 200


def test_browse_navigation_and_file_filter(client, tmp_path):
    folder = tmp_path / 'folder with spaces'
    folder.mkdir()
    (tmp_path / 'file.gguf').write_bytes(b'GGUF')
    result = client.get('/api/settings/browse', params={'path':str(tmp_path)}).json()
    assert all(e['directory'] for e in result['entries'])
    assert any(e['path'] == str(folder) for e in result['entries'])
    result = client.get('/api/settings/browse', params={'path':str(tmp_path), 'mode':'file'}).json()
    assert any(e['name'] == 'file.gguf' and not e['directory'] for e in result['entries'])
    assert result['parent'] == str(tmp_path.parent)
    assert client.get('/api/settings/browse', params={'path':str(tmp_path / 'missing')}).status_code == 404
    assert client.get('/api/settings/browse', params={'path':'relative'}).status_code == 422


def test_browse_permission_error(client, tmp_path, monkeypatch):
    def fail(*args):
        raise PermissionError()
    monkeypatch.setattr('app.routers.settings.os.scandir', fail)
    assert client.get('/api/settings/browse', params={'path':str(tmp_path)}).status_code == 403


def test_newer_settings_format_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.setenv('LLAMAPANEL_DATA_DIR', str(tmp_path))
    path = tmp_path / 'settings.json'
    text = '{"version": 999, "settings": {}}'
    path.write_text(text)
    with pytest.raises(NewerFormatError):
        Settings.from_env()
    assert path.read_text() == text


def test_defaults_platform_binary(tmp_path, monkeypatch):
    monkeypatch.setenv('LLAMAPANEL_DATA_DIR', str(tmp_path))
    monkeypatch.setattr('app.settings.sys.platform', 'win32')
    assert Settings.from_env().server_bin == 'llama-server.exe'
    monkeypatch.setattr('app.settings.sys.platform', 'darwin')
    assert Settings.from_env().server_bin == 'llama-server'


def test_changed_binary_preserves_managers_and_replaces_catalog(client, tmp_path):
    manager = client.app.state.manager
    inspector = client.app.state.inspector
    # No process-control method is involved in saving global settings.
    assert client.put('/api/settings', json=payload(tmp_path)).status_code == 200
    assert client.app.state.manager is manager
    assert client.app.state.inspector is not inspector
    assert client.app.state.instances.settings is client.app.state.settings
