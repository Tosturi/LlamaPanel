import asyncio
import hashlib
import struct

import httpx
import pytest

from app import model_downloads as downloads
from app.gguf_scanner import scan

GGUF = b'GGUF' + struct.pack('<IQQ', 3, 0, 0)


def metadata(names):
    return {'sha': 'a' * 40, 'siblings': [{'rfilename': name, 'lfs': {'size': len(GGUF),
        'sha256': hashlib.sha256(GGUF).hexdigest()}} for name in names]}


@pytest.mark.parametrize('source', ['org/repo:TQ1_0', '-hf org/repo:TQ1_0'])
def test_source(source):
    assert downloads.parse_source(source) == ('org/repo', 'TQ1_0')


@pytest.mark.parametrize('source', ['../repo:Q8_0', 'https://evil.test/a', 'org/repo; touch x', '-hf org/repo --port 80'])
def test_reject_source(source):
    with pytest.raises(ValueError):
        downloads.parse_source(source)


def test_quantization_and_split():
    data = metadata(['model-PTQ1_0.gguf', 'model-TQ1_0.gguf', 'mmproj-TQ1_0.gguf'])
    assert [c['name'] for c in downloads.candidates(data, 'tq1_0')] == ['model-PTQ1_0.gguf', 'model-TQ1_0.gguf']
    data = metadata(['Q8_0/model-Q8_0-00001-of-00002.gguf', 'Q8_0/model-Q8_0-00002-of-00002.gguf'])
    assert len(downloads.candidates(data, 'Q8_0')[0]['files']) == 2
    data['siblings'].pop()
    with pytest.raises(ValueError, match='missing split'):
        downloads.candidates(data, 'Q8_0')


def test_projectors_ignore_model_quantization():
    data = metadata(['model-Q8_0.gguf', 'mmproj-F16.gguf', 'mmproj-Q5_0.gguf'])
    assert len(downloads.candidates(data, 'Q8_0')) == 1
    assert len(downloads.candidates(data, None, projector=True)) == 2
    assert downloads.candidates(metadata(['model.gguf']), None, projector=True) == []


@pytest.mark.asyncio
@pytest.mark.parametrize('append', [False, True])
async def test_projector_download_without_duplicate_models(tmp_path, monkeypatch, append):
    calls = []
    def handler(request):
        if '/api/' in request.url.path:
            return httpx.Response(200, json=metadata(['model-Q8_0.gguf', 'mmproj-F16.gguf']))
        calls.append(request.url.path)
        return httpx.Response(200, content=GGUF)
    mock_hf(monkeypatch, handler)
    service = downloads.ModelDownloads()
    plan = await service.resolve('org/repo:Q8_0')
    assert len(plan['projectors']) == 1
    if append:
        service.start(plan['id'], 0, tmp_path)
        await service.task
        calls.clear()
    service.start(plan['id'], 0, tmp_path, projector=0)
    await service.task
    assert service.state['phase'] == 'complete'
    assert len(calls) == (1 if append else 2)
    assert service.state['downloaded'] == service.state['total'] == len(GGUF) * len(calls)
    assert len(scan(tmp_path)) == 1
    assert len(list(tmp_path.glob('org/repo/*/projector-*/*.gguf'))) == 1
    with pytest.raises(ValueError, match='available projector'):
        service.start(plan['id'], 0, tmp_path, projector=10)


@pytest.mark.asyncio
async def test_projector_failure_preserves_existing_model(tmp_path, monkeypatch):
    def handler(request):
        if '/api/' in request.url.path:
            return httpx.Response(200, json=metadata(['model.gguf', 'mmproj.gguf']))
        return httpx.Response(200, content=b'corrupt' if 'mmproj' in request.url.path else GGUF)
    mock_hf(monkeypatch, handler)
    service = downloads.ModelDownloads()
    plan = await service.resolve('org/repo')
    service.start(plan['id'], 0, tmp_path)
    await service.task
    before = scan(tmp_path)[0]
    service.start(plan['id'], 0, tmp_path, projector=0)
    await service.task
    assert service.state['phase'] == 'failed'
    assert scan(tmp_path) == [before]
    assert not list(tmp_path.glob('org/repo/*/projector-*'))


@pytest.mark.parametrize('path', ['../escape.gguf', '/escape.gguf', 'folder\\file.gguf', 'CON.gguf', 'file:stream.gguf', 'folder./x.gguf'])
def test_unsafe_paths(path):
    with pytest.raises(ValueError):
        downloads.candidates(metadata([path]), None)


def mock_hf(monkeypatch, handler):
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: client(transport=httpx.MockTransport(handler), **kw))


@pytest.mark.asyncio
@pytest.mark.parametrize('payload,phase', [(GGUF, 'complete'), (b'bad', 'failed'), (b'x' * len(GGUF), 'failed')])
async def test_download_publish_integrity_and_scanner(tmp_path, monkeypatch, payload, phase):
    def handler(request):
        if '/api/' in request.url.path:
            return httpx.Response(200, json=metadata(['sub/model-Q8_0.gguf']))
        assert '/resolve/' + 'a' * 40 + '/' in request.url.path
        assert scan(tmp_path) == []
        return httpx.Response(200, content=payload)
    mock_hf(monkeypatch, handler)
    service = downloads.ModelDownloads()
    plan = await service.resolve('-hf org/repo:Q8_0')
    service.start(plan['id'], 0, tmp_path)
    with pytest.raises(ValueError, match='already running'):
        service.start(plan['id'], 0, tmp_path)
    await service.task
    assert service.state['phase'] == phase
    models = scan(tmp_path)
    assert len(models) == (1 if phase == 'complete' else 0)
    assert not list((tmp_path / downloads.STORE).glob('.partial-*'))
    if models:
        assert models[0].id.startswith('hf/org/repo/Q8_0/')
        assert (tmp_path / 'org/repo/Q8_0/model-Q8_0.gguf').is_file()
        assert models[0].display_name == 'model-Q8_0'
        service.start(plan['id'], 0, tmp_path)
        await service.task
        assert service.state['phase'] == 'failed'
        assert len(scan(tmp_path)) == 1


@pytest.mark.asyncio
async def test_redirect_credentials_and_deny_external(monkeypatch):
    monkeypatch.setenv('HF_TOKEN', 'test-token')
    calls = []
    def handler(request):
        calls.append((request.url.host, request.headers.get('Authorization')))
        if request.url.host == 'huggingface.co':
            return httpx.Response(302, headers={'location': 'https://cas-bridge.xethub.hf.co/file'})
        return httpx.Response(200, content=GGUF)
    mock_hf(monkeypatch, handler)
    async with httpx.AsyncClient() as client:
        response = await downloads.stream_hf(client, 'https://huggingface.co/file')
        await response.aclose()
        with pytest.raises(ValueError, match='Unexpected'):
            await downloads.stream_hf(client, 'https://127.0.0.1/file')
    assert calls == [('huggingface.co', 'Bearer test-token'), ('cas-bridge.xethub.hf.co', None)]


@pytest.mark.asyncio
async def test_cancel_during_transfer(tmp_path, monkeypatch):
    started = asyncio.Event()
    async def handler(request):
        if '/api/' in request.url.path:
            return httpx.Response(200, json=metadata(['model.gguf']))
        started.set()
        await asyncio.Event().wait()
    mock_hf(monkeypatch, handler)
    service = downloads.ModelDownloads()
    plan = await service.resolve('org/repo')
    service.start(plan['id'], 0, tmp_path)
    await asyncio.wait_for(started.wait(), timeout=2)
    await service.cancel()
    assert service.state['phase'] == 'cancelled'
    assert scan(tmp_path) == []
    assert not list((tmp_path / downloads.STORE).glob('.partial-*'))


@pytest.mark.asyncio
async def test_cancel_before_task_starts(tmp_path):
    service = downloads.ModelDownloads()
    service.plan = {'id': 'test', 'repository': 'org/repo', 'revision': 'a' * 40,
                    'choices': downloads.candidates(metadata(['model.gguf']), None)}
    service.start('test', 0, tmp_path)
    await service.cancel()
    assert service.state['phase'] == 'cancelled'


def test_scanner_ignores_partial_downloads(tmp_path):
    folder = tmp_path / downloads.STORE / '.partial-test'
    folder.mkdir(parents=True)
    (folder / 'model.gguf').write_bytes(GGUF)
    assert scan(tmp_path) == []


def test_routes_and_update_interlock(client, monkeypatch):
    service = client.app.state.model_downloads
    async def resolve(source):
        service.plan = {'id': 'test', 'repository': 'org/repo', 'revision': 'a' * 40,
                        'choices': downloads.candidates(metadata(['model.gguf']), None)}
        return service.plan
    monkeypatch.setattr(service, 'resolve', resolve)
    assert client.post('/api/model-downloads/resolve', json={'source': 'org/repo'}, headers={'Origin': 'https://evil.test'}).status_code == 403
    assert client.post('/api/model-downloads/resolve', json={'source': 'org/repo'}).status_code == 200
    assert client.post('/api/model-downloads', json={'plan_id': 'stale', 'choice': 0}).status_code == 409
    client.app.state.updates.phase = 'preparing'
    assert client.post('/api/model-downloads', json={'plan_id': 'test', 'choice': 0}).status_code == 409


@pytest.mark.asyncio
async def test_readable_revisions_and_legacy_paths(tmp_path, monkeypatch):
    mock_hf(monkeypatch, lambda request: httpx.Response(200, content=GGUF))
    service = downloads.ModelDownloads()
    model = downloads.candidates(metadata(['model-Q4_K_M.gguf']), None)[0]
    plan = {'id': 'test', 'repository': 'unsloth/Qwen-GGUF',
            'revision': 'a' * 40, 'choices': [model]}
    service.plan = plan
    service.start('test', 0, tmp_path)
    await service.task
    assert service.state['phase'] == 'complete'
    original = tmp_path / 'unsloth/Qwen-GGUF/Q4_K_M/model-Q4_K_M.gguf'
    assert original.read_bytes() == GGUF
    plan['revision'] = 'b' * 40
    service.start('test', 0, tmp_path)
    await service.task
    assert service.state['phase'] == 'complete'
    assert len(scan(tmp_path)) == 2
    assert original.read_bytes() == GGUF
    # Old downloads retain their paths and IDs.
    plan['revision'] = 'c' * 40
    identity = hashlib.sha256(f"{plan['repository']}@{plan['revision']}:{model['name']}".encode()).hexdigest()[:24]
    legacy = tmp_path / downloads.STORE / identity
    legacy.mkdir()
    (legacy / 'model-Q4_K_M.gguf').write_bytes(GGUF)
    service.start('test', 0, tmp_path)
    await service.task
    assert service.state['phase'] == 'failed'
    assert len(scan(tmp_path)) == 3
    assert any(m.id.startswith(f'hf/{identity}/') for m in scan(tmp_path))


@pytest.mark.parametrize('repo', ['CON/repo', 'org/repo.'])
def test_readable_rejects_windows_unsafe_names(tmp_path, repo):
    with pytest.raises(ValueError):
        downloads.readable_target(tmp_path, {'repository': repo},
                                  {'name': 'model-Q8_0.gguf'}, 'a' * 24)


def test_readable_does_not_follow_author_symlink(tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    try:
        (tmp_path / 'org').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('Directory symlinks are unavailable')
    with pytest.raises(ValueError, match='symlink'):
        downloads.readable_target(tmp_path, {'repository': 'org/repo'},
                                  {'name': 'model-Q8_0.gguf'}, 'a' * 24)
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize('name,label', [
    ('model-Q4_K_M.gguf', 'Q4_K_M'),
    ('Q8_0/model-Q8_0', 'Q8_0'),
    ('model-PTQ1_0.gguf', 'PTQ1_0'),
    ('model-BF16.gguf', 'BF16'),
    ('model.gguf', 'model'),
])
def test_readable_folder_labels(tmp_path, name, label):
    target = downloads.readable_target(tmp_path, {'repository': 'org/repo'},
                                       {'name': name}, 'a' * 24)
    assert target == tmp_path / 'org/repo' / label


def test_readable_preserves_user_owned_folder(tmp_path):
    occupied = tmp_path / 'org/repo/Q8_0'
    occupied.mkdir(parents=True)
    (occupied / 'model.gguf').write_bytes(GGUF)
    target = downloads.readable_target(tmp_path, {'repository': 'org/repo'},
                                       {'name': 'model-Q8_0.gguf'}, 'a' * 24)
    assert target.name == 'Q8_0-' + 'a' * 24
    assert (occupied / 'model.gguf').read_bytes() == GGUF
