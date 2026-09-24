"""Hugging Face GGUF downloads, staged outside the visible model library."""
import asyncio
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx

STORE = '.hf-models'
SPLIT = re.compile(r'^(.*)-(\d{5})-of-(\d{5})\.gguf$', re.I)


def parse_source(source):
    source = re.sub(r'^-hf\s+', '', source.strip())
    match = re.fullmatch(r'([\w-]+/[\w.-]+)(?::([A-Za-z0-9_]+))?', source, re.ASCII)
    if not match or '..' in match[1]:
        raise ValueError('Use owner/repository:quantization, optionally preceded by -hf.')
    return match[1], match[2]


def safe_path(name):
    parts = name.split('/')
    if (not parts or any(not p or p in ('.', '..') or p.endswith((' ', '.')) for p in parts)
            or re.search(r'[\\\x00-\x1f<>:"|?*]', name)
            or any(re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', p, re.I) for p in parts)):
        raise ValueError('Repository contains an unsafe file path.')
    return name


def candidates(data, quant):
    groups = {}
    for sibling in data.get('siblings', []):
        name = sibling['rfilename']
        if not name.lower().endswith('.gguf') or 'mmproj' in name.lower():
            continue
        # Match llama.cpp's tag search: case-insensitive tag followed by . or -.
        # In particular, Bonsai's TQ1_0 shorthand also matches PTQ1_0 filenames.
        if quant and not re.search(re.escape(quant) + r'[.\-]', name, re.I):
            continue
        safe_path(name)
        lfs = sibling.get('lfs') or {}
        size, digest = lfs.get('size'), lfs.get('sha256')
        if not isinstance(size, int) or size < 4 or not re.fullmatch(r'[a-fA-F0-9]{64}', digest or ''):
            raise ValueError('GGUF size or SHA-256 is unavailable for this repository.')
        split = SPLIT.fullmatch(name)
        key = split[1] if split else name
        groups.setdefault(key, []).append({'path': name, 'size': size, 'sha256': digest.lower()})
    result = []
    for name, files in sorted(groups.items()):
        files.sort(key=lambda f: f['path'])
        split = SPLIT.fullmatch(files[0]['path'])
        if split:
            count = int(split[3])
            expected = [f'{name}-{i:05d}-of-{count:05d}.gguf' for i in range(1, count + 1)]
            if [f['path'].lower() for f in files] != [p.lower() for p in expected]:
                raise ValueError('The repository is missing split model parts.')
        result.append({'name': name, 'files': files, 'size': sum(f['size'] for f in files)})
    if not result:
        raise ValueError('No matching GGUF model found. Check the repository and quantization.')
    return result


async def stream_hf(client, url):
    """Follow only HF/CDN HTTPS redirects; never forward the token to a CDN."""
    for _ in range(8):
        parsed = urlsplit(url)
        host = parsed.hostname or ''
        if (parsed.scheme != 'https' or parsed.port not in (None, 443) or parsed.username
                or not (host == 'huggingface.co' or host.endswith(('.huggingface.co', '.hf.co')))):
            raise ValueError('Unexpected download redirect.')
        token = os.environ.get('HF_TOKEN')
        headers = {'Authorization': f'Bearer {token}'} if token and host == 'huggingface.co' else {}
        response = await client.send(client.build_request('GET', url, headers=headers), stream=True)
        if response.is_redirect:
            url = str(response.next_request.url)
            await response.aclose()
            continue
        if response.status_code != 200:
            code = response.status_code
            await response.aclose()
            if code in (401, 403):
                raise ValueError('Access denied. For gated/private models, grant access on Hugging Face and set HF_TOKEN before starting the panel.')
            raise ValueError(f'Hugging Face returned HTTP {code}.')
        return response
    raise ValueError('Too many download redirects.')


class ModelDownloads:
    def __init__(self):
        self.plan = None
        self.task = None
        self.state = {'id': '', 'phase': 'idle', 'name': '', 'directory': '', 'downloaded': 0, 'total': 0, 'message': ''}

    @property
    def busy(self):
        return self.task is not None and not self.task.done()

    async def resolve(self, source):
        repo, quant = parse_source(source)
        async with httpx.AsyncClient(timeout=30) as client:
            response = await stream_hf(client, f'https://huggingface.co/api/models/{repo}?blobs=true')
            try:
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 8 * 1024 * 1024:
                        raise ValueError('Repository metadata is too large.')
                    chunks.append(chunk)
                data = json.loads(b''.join(chunks))
            finally:
                await response.aclose()
        revision = data.get('sha', '')
        if not re.fullmatch('[a-f0-9]{40}', revision):
            raise ValueError('Cannot resolve a fixed repository revision.')
        plan = {'id': uuid4().hex, 'repository': repo, 'revision': revision, 'choices': candidates(data, quant)}
        self.plan = plan
        return plan

    def start(self, plan_id, choice, directory):
        if self.busy:
            raise ValueError('A model download is already running.')
        if not self.plan or self.plan['id'] != plan_id or not 0 <= choice < len(self.plan['choices']):
            raise ValueError('Preview this repository again before downloading.')
        plan, model = self.plan, self.plan['choices'][choice]
        directory = directory.resolve()
        self.state = {'id': uuid4().hex, 'phase': 'downloading', 'name': model['name'],
                      'directory': str(directory), 'downloaded': 0, 'total': model['size'], 'message': ''}
        self.task = asyncio.create_task(self.download(plan, model, directory))

    async def download(self, plan, model, directory):
        stage = None
        try:
            store = directory / STORE
            store.mkdir(parents=True, exist_ok=True)
            if store.is_symlink():
                raise ValueError('The download storage directory cannot be a symlink.')
            identity = hashlib.sha256(f"{plan['repository']}@{plan['revision']}:{model['name']}".encode()).hexdigest()[:24]
            target = store / identity
            if target.exists():
                raise ValueError('This model revision is already downloaded.')
            if shutil.disk_usage(store).free < model['size'] + 64 * 1024 * 1024:
                raise ValueError('Not enough free disk space.')
            stage = store / ('.partial-' + self.state['id'])
            stage.mkdir()
            async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=20), headers={'Accept-Encoding': 'identity'}) as client:
                for file in model['files']:
                    self.state['message'] = PurePosixPath(file['path']).name
                    url = f"https://huggingface.co/{plan['repository']}/resolve/{plan['revision']}/{quote(file['path'], safe='/')}"
                    response = await stream_hf(client, url)
                    digest, received = hashlib.sha256(), 0
                    filename = PurePosixPath(file['path']).name
                    destination = stage / (filename[:-5] + '.gguf')
                    try:
                        with destination.open('xb') as output:
                            async for chunk in response.aiter_bytes(1024 * 1024):
                                received += len(chunk)
                                if received > file['size']:
                                    raise ValueError('Downloaded file exceeds its expected size.')
                                output.write(chunk)
                                digest.update(chunk)
                                self.state['downloaded'] += len(chunk)
                            output.flush()
                            os.fsync(output.fileno())
                    finally:
                        await response.aclose()
                    if received != file['size'] or digest.hexdigest() != file['sha256']:
                        raise ValueError('Download is incomplete or its SHA-256 does not match.')
                    with destination.open('rb') as check:
                        if check.read(4) != b'GGUF':
                            raise ValueError('Downloaded file is not GGUF.')
            stage.rename(target)
            self.state.update(phase='complete', message='Model added to the library.')
        except asyncio.CancelledError:
            self.state.update(phase='cancelled', message='Download cancelled.')
        except (OSError, ValueError, httpx.HTTPError) as exc:
            # HTTP exceptions can contain signed URLs; do not expose them.
            message = 'Network error. Retry the download.' if isinstance(exc, httpx.HTTPError) else str(exc)
            self.state.update(phase='failed', message=message)
        finally:
            if stage and stage.exists():
                shutil.rmtree(stage)

    async def cancel(self):
        if self.busy:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                self.state.update(phase='cancelled', message='Download cancelled.')
