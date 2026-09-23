import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import shutil
import stat
import subprocess
import sys
import time
from types import SimpleNamespace
import zipfile
import urllib.request

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app import update_runtime as runtime
from app import updates


def release():
    name = 'LlamaPanel-v9.0.0.zip'
    return {'tag_name': 'v9.0.0', 'body': 'Changes', 'assets': [
        {'name': name + suffix, 'browser_download_url': f'https://github.com/Tosturi/LlamaPanel/releases/download/v9.0.0/{name}{suffix}'}
        for suffix in ('', '.sha256')]}


def archive_bytes(extra=None, manifest=None):
    files = {name: '' for name in ('run.py', 'settings.defaults.json', 'backend/requirements.txt',
             'backend/app/main.py', 'backend/app/update_runtime.py', 'frontend/dist/index.html')}
    files.update({'VERSION': '9.0.0', 'release.json': json.dumps(manifest or {'updater_protocol': 1, 'python_min': [3, 12]})})
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as bundle:
        for name, value in files.items():
            bundle.writestr('LlamaPanel/' + name, value)
        if extra:
            name, value = extra
            if isinstance(name, str):
                # Write the actual hostile bytes, bypassing ZipInfo's native
                # separator normalization and NUL truncation on construction.
                entry = zipfile.ZipInfo()
                entry.filename = name
            else:
                entry = name
            bundle.writestr(entry, value)
    return stream.getvalue()


def test_release_selection():
    selected = updates.select_release(release())
    assert selected['version'] == '9.0.0'
    assert updates.version('v1.10.0') > updates.version('1.9.9')


@pytest.mark.parametrize('change', [
    {'prerelease': True}, {'draft': True}, {'tag_name': 'v9.0.0-rc1'}, {'assets': []},
    {'assets': [{'name': 'LlamaPanel-v9.0.0.zip', 'browser_download_url': 'https://evil.test/a'},
                {'name': 'LlamaPanel-v9.0.0.zip.sha256', 'browser_download_url': 'https://evil.test/b'}]},
])
def test_reject_invalid_release(change):
    with pytest.raises(ValueError):
        updates.select_release(release() | change)


@pytest.mark.parametrize('path', ['../escape', '/absolute', 'LlamaPanel/../../escape',
    'LlamaPanel/backend/app/evil\\path', 'LlamaPanel/backend/app/file:stream',
    'LlamaPanel/backend/app/file\x00hidden',
    'LlamaPanel/backend/app/file.', 'LlamaPanel/VERSION', 'LlamaPanel/version', 'LlamaPanel/.venv/config'])
def test_reject_archive_paths(tmp_path, path):
    archive = tmp_path / 'release.zip'
    archive.write_bytes(archive_bytes((path, 'bad')))
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.infolist()[-1].orig_filename == path
    with pytest.raises(ValueError):
        updates.extract_release(archive, tmp_path / 'out', '9.0.0')
    assert not (tmp_path / 'out').exists()


def test_archive_symlink_and_compatibility(tmp_path):
    archive = tmp_path / 'release.zip'
    link = zipfile.ZipInfo('LlamaPanel/backend/app/link')
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    archive.write_bytes(archive_bytes((link, '/tmp')))
    with pytest.raises(ValueError, match='Unsafe'):
        updates.extract_release(archive, tmp_path / 'out', '9.0.0')
    for manifest, message in [({'updater_protocol': 2}, 'newer updater'),
                               ({'updater_protocol': 1, 'python_min': [99, 0]}, 'newer Python')]:
        archive.write_bytes(archive_bytes(manifest=manifest))
        with pytest.raises(ValueError, match=message):
            updates.extract_release(archive, tmp_path / 'out', '9.0.0')
    archive.write_bytes(archive_bytes())
    with pytest.raises(ValueError, match='version does not match'):
        updates.extract_release(archive, tmp_path / 'out', '9.0.1')
    assert updates.extract_release(archive, tmp_path / 'out', '9.0.0').name == 'LlamaPanel'


@pytest.mark.asyncio
async def test_download_redirect_limits(monkeypatch, tmp_path):
    real_client = httpx.AsyncClient
    def handler(request):
        if request.url.path == '/redirect':
            return httpx.Response(302, headers={'Location': 'https://release-assets.githubusercontent.com/file'})
        if request.url.path == '/bad':
            return httpx.Response(302, headers={'Location': 'http://127.0.0.1/secret'})
        return httpx.Response(200, content=b'archive')
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    assert await updates.fetch_bytes('https://github.com/redirect', 7) == b'archive'
    target = tmp_path / 'zip'
    await updates.fetch_bytes('https://github.com/redirect', 7, target)
    assert target.read_bytes() == b'archive'
    with pytest.raises(ValueError, match='size'):
        await updates.fetch_bytes('https://github.com/file', 6)
    with pytest.raises(ValueError, match='Untrusted'):
        await updates.fetch_bytes('https://github.com/bad', 100)


@pytest.fixture
def service(tmp_path, monkeypatch, settings):
    install = tmp_path / 'install'
    install.mkdir()
    (install / 'release.json').write_text('{}')
    monkeypatch.setenv('LLAMAPANEL_INSTALL_ROOT', str(install))
    monkeypatch.setenv('LLAMAPANEL_MANAGED', '1')
    app = SimpleNamespace(state=SimpleNamespace(settings=settings, request_restart=lambda: None))
    result = updates.UpdateService(app)
    result.release = updates.select_release(release())
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['checksum', 'dependencies', None])
async def test_staging_never_restarts_before_validation(service, monkeypatch, failure):
    payload = archive_bytes()
    async def download(url, limit, target=None):
        if target:
            target.write_bytes(payload)
            return b''
        digest = '0' * 64 if failure == 'checksum' else hashlib.sha256(payload).hexdigest()
        return f'{digest}  LlamaPanel-v9.0.0.zip'.encode()
    monkeypatch.setattr(updates, 'fetch_bytes', download)
    def environment(*args):
        if failure == 'dependencies':
            raise RuntimeError('pip failed')
    monkeypatch.setattr(updates, 'prepare_environment', environment)
    restarted = []
    service.app.state.request_restart = lambda: restarted.append(True)
    service.start('9.0.0')
    with pytest.raises(ValueError, match='already'):
        service.start('9.0.0')
    await service.task
    assert restarted == ([] if failure else [True])
    assert (service.directory / 'request.json').exists() == (failure is None)
    assert service.status()['phase'] == ('failed' if failure else 'restarting')


def test_install_modes(service, monkeypatch):
    assert service.unavailable_reason() is None
    monkeypatch.delenv('LLAMAPANEL_MANAGED')
    assert 'python run.py' in service.unavailable_reason()
    (service.install / '.git').write_text('gitdir: somewhere')
    assert 'Git checkouts' in service.unavailable_reason()


def test_dependency_install_failure_never_marks_environment_ready(tmp_path, monkeypatch):
    root = tmp_path / 'candidate'
    (root / 'backend').mkdir(parents=True)
    (root / 'backend/requirements.txt').write_text('example==1.0')
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        if 'venv' in args:
            python = runtime.python_in(root)
            python.parent.mkdir(parents=True)
            python.touch()
        else:
            raise subprocess.CalledProcessError(1, args)
    monkeypatch.setattr(subprocess, 'run', run)
    with pytest.raises(subprocess.CalledProcessError):
        runtime.ensure_environment(root)
    assert not (root / '.venv/requirements.sha256').exists()
    assert calls[-1][0] == str(runtime.python_in(root))
    assert calls[-1][-1] == str(root / 'backend/requirements.txt')
    calls.clear()
    monkeypatch.setattr(subprocess, 'run', lambda args, **kw: calls.append(args))
    runtime.ensure_environment(root)
    runtime.ensure_environment(root)
    assert len(calls) == 1  # successful requirements fingerprint skips repeat pip


def test_install_request_guards(service, settings):
    app = create_app(settings)
    with TestClient(app, base_url='http://localhost', client=('127.0.0.1', 50000)) as client:
        app.state.updates = service
        app.state.request_restart = lambda: None
        assert client.post('/api/updates/install', json={'version': '9.0.0'}, headers={'Origin': 'https://evil.test'}).status_code == 403
        assert client.post('/api/updates/install', json={'version': '9.0.0'}, headers={'Host': 'evil.test'}).status_code == 403
        assert client.post('/api/updates/install', json={'version': '8.0.0'}).status_code == 409
        runtime.write_json(service.directory / 'activation.json', {})
        assert client.get('/api/models').status_code == 503
        assert client.get('/api/updates/ready').status_code == 200
        (service.directory / 'activation.json').unlink()
    with TestClient(app, base_url='http://localhost', client=('192.0.2.1', 50000)) as client:
        app.state.updates = service
        assert not client.get('/api/updates').json()['supported']
        assert client.post('/api/updates/install', json={'version': '9.0.0'}).status_code == 403


def activation_fixture(tmp_path):
    install = tmp_path / 'install'
    root = runtime.release_root(install, 'a' * 32)
    root.mkdir(parents=True)
    data = tmp_path / 'data'
    data.mkdir()
    runtime.write_json(data / 'settings.json', {'old': True})
    return install, root, data, {'slot': 'a' * 32, 'version': '9.0.0', 'data_dir': str(data), 'host': '127.0.0.1', 'port': 8000}


@pytest.mark.parametrize('healthy', [True, False])
def test_activation_and_data_rollback(tmp_path, healthy):
    install, root, data, request = activation_fixture(tmp_path)
    proc = SimpleNamespace(poll=lambda: 0)
    def spawn(*args):
        runtime.write_json(data / 'settings.json', {'new': True})
        runtime.write_json(data / 'instances.json', {'new': True})
        return proc
    if healthy:
        _, state = runtime.activate(install, {'current': None}, request, [], spawn, lambda *a: True)
        assert state['current'] == 'a' * 32
        assert runtime.read_json(data / 'settings.json') == {'new': True}
    else:
        with pytest.raises(RuntimeError, match='not become ready'):
            runtime.activate(install, {'current': None}, request, [], spawn, lambda *a: False)
        assert runtime.read_json(data / 'settings.json') == {'old': True}
        assert not (data / 'instances.json').exists()
        assert runtime.read_json(install / '.updates/current.json')['current'] is None
    assert not (install / '.updates/activation.json').exists()


def test_interrupted_recovery_and_live_worker_lock(tmp_path):
    install, root, data, request = activation_fixture(tmp_path)
    runtime.snapshot(data, root.parent / 'data-backup')
    runtime.write_json(install / '.updates/activation.json', request | {'previous': None})
    runtime.write_json(data / 'settings.json', {'incompatible': True})
    runtime.write_json(install / '.updates/worker-token.json', 'active')
    with runtime.worker_guard(install, 'active'):
        with pytest.raises(OSError):
            runtime.recover(install)
        assert runtime.read_json(data / 'settings.json') == {'incompatible': True}
    runtime.recover(install)
    assert runtime.read_json(data / 'settings.json') == {'old': True}
    with pytest.raises(RuntimeError, match='superseded'):
        with runtime.worker_guard(install, 'active'):
            pytest.fail('Stale worker acquired lock')


@pytest.mark.parametrize('healthy', [True, False])
def test_real_candidate_process(tmp_path, healthy):
    install, root, data, request = activation_fixture(tmp_path)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        request['port'] = sock.getsockname()[1]
    script = root / 'run.py'
    script.write_text('''import json, os, sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
Path(os.environ['LLAMAPANEL_DATA_DIR'], 'settings.json').write_text('{"changed": true}')
if sys.argv[2] == 'False': sys.exit(1)
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(json.dumps({'token': os.environ['LLAMAPANEL_LAUNCH_TOKEN'], 'version': '9.0.0'}).encode())
    def log_message(self, *args): pass
HTTPServer(('127.0.0.1', int(sys.argv[1])), Handler).serve_forever()
''')
    def spawn(root, install, args, data_dir, token):
        return subprocess.Popen([sys.executable, str(script), str(request['port']), str(healthy)],
             env=dict(os.environ, LLAMAPANEL_DATA_DIR=str(data_dir), LLAMAPANEL_LAUNCH_TOKEN=token))
    if healthy:
        proc, _ = runtime.activate(install, {'current': None}, request, [], spawn)
        try:
            assert proc.poll() is None
            assert runtime.read_json(install / '.updates/current.json')['current'] == request['slot']
        finally:
            runtime.stop_worker(proc)
    else:
        with pytest.raises(RuntimeError):
            runtime.activate(install, {'current': None}, request, [], spawn)
        assert runtime.read_json(data / 'settings.json') == {'old': True}


@pytest.mark.skipif(os.name == 'nt', reason='Uses a POSIX test interpreter shim; platform tests cover Windows worker activation')
def test_release_launcher_restart_and_persistent_selection(tmp_path):
    """Exercise real run.py, worker lock, graceful restart and next-launch pointer."""
    source = Path(__file__).resolve().parents[2]
    install = tmp_path / 'release'
    install.mkdir()
    for name in ('run.py', 'VERSION', 'settings.defaults.json'):
        shutil.copy2(source / name, install / name)
    shutil.copytree(source / 'backend/app', install / 'backend/app', ignore=shutil.ignore_patterns('__pycache__'))
    main_file = install / 'backend/app/main.py'
    main_file.write_text(main_file.read_text().replace(
        '    app.include_router(models.router)',
        "    app.post('/test-restart')(lambda: app.state.request_restart())\n    app.include_router(models.router)"))
    shutil.copy2(source / 'backend/requirements.txt', install / 'backend/requirements.txt')
    runtime.write_json(install / 'release.json', {'updater_protocol': 1})
    candidate = runtime.release_root(install, 'b' * 32)
    shutil.copytree(install, tmp_path / 'candidate')
    candidate.parent.mkdir(parents=True)
    shutil.move(str(tmp_path / 'candidate'), candidate)
    (candidate / 'VERSION').write_text('9.0.0')
    # Reuse the test interpreter without pip/network. Real dependency staging
    # is tested separately; each installation still gets its own marker.
    import shlex
    for root in (install, candidate):
        python = runtime.python_in(root)
        python.parent.mkdir(parents=True)
        python.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' "$@"\n')
        python.chmod(0o755)
        (root / '.venv/requirements.sha256').write_text(hashlib.sha256((root / 'backend/requirements.txt').read_bytes()).hexdigest())
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    data = tmp_path / 'data'
    args = [sys.executable, str(install / 'run.py'), '--port', str(port), '--data-dir', str(data)]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def await_version(expected):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                with opener.open(f'http://127.0.0.1:{port}/api/health', timeout=.5) as response:
                    if json.load(response)['version'] == expected:
                        return
            except (OSError, ValueError):
                pass
            time.sleep(.1)
        pytest.fail('Panel did not become ready')
    import psutil
    env = {key: value for key, value in os.environ.items() if not key.startswith('LLAMAPANEL_')}
    def stop_tree(proc):
        children = psutil.Process(proc.pid).children(recursive=True) if proc.poll() is None else []
        for child in children:
            child.terminate()
        try:
            proc.wait(timeout=10)
        finally:
            runtime.stop_worker(proc)
    with (tmp_path / 'launcher.log').open('w') as log:
        proc = subprocess.Popen(args, env=env, stdout=log, stderr=log)
        try:
            await_version((install / 'VERSION').read_text().strip())
            runtime.write_json(install / '.updates/request.json', {'slot': 'b' * 32, 'version': '9.0.0',
                'data_dir': str(data), 'host': '127.0.0.1', 'port': port})
            with opener.open(urllib.request.Request(f'http://127.0.0.1:{port}/test-restart', data=b''), timeout=2):
                pass
            await_version('9.0.0')
            deadline = time.monotonic() + 5
            while not (install / '.updates/current.json').exists() and time.monotonic() < deadline:
                time.sleep(.1)
            assert runtime.read_json(install / '.updates/current.json')['current'] == 'b' * 32
        finally:
            stop_tree(proc)
        proc = subprocess.Popen(args, env=env, stdout=log, stderr=log)
        try:
            await_version('9.0.0')
        finally:
            stop_tree(proc)
