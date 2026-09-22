"""Download only official stable release assets and stage an isolated runtime."""
import asyncio
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import time
from urllib.parse import urlsplit
from uuid import uuid4
import zipfile

import httpx

from app import __version__
from app.settings import ROOT
from app.update_runtime import PROTOCOL, ensure_environment, read_json, write_json

REPOSITORY = 'Tosturi/LlamaPanel'
LATEST = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
MAX_ARCHIVE = 256 * 1024 * 1024
MAX_EXPANDED = 1024 * 1024 * 1024


def prepare_environment(root, log_path):
    # The thread owns the stream even if the awaiting task is cancelled.
    with log_path.open('w') as log:
        ensure_environment(root, log)


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'v?\d+\.\d+\.\d+', value):
        raise ValueError('Only stable x.y.z releases are supported')
    return tuple(map(int, value.removeprefix('v').split('.')))


def official_asset(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.netloc != 'github.com'
            or not parsed.path.startswith(f'/{REPOSITORY}/releases/download/')):
        raise ValueError('Release asset is not hosted in the official repository')
    return url


def select_release(data):
    tag = data['tag_name']
    version(tag)
    if data.get('draft') or data.get('prerelease'):
        raise ValueError('Pre-releases are not supported')
    name = f'LlamaPanel-v{tag.removeprefix("v")}.zip'
    assets = {item['name']: item for item in data['assets']}
    if name not in assets or name + '.sha256' not in assets:
        raise ValueError('This release does not contain a ZIP and checksum')
    return {'version': tag.removeprefix('v'), 'notes': str(data.get('body') or '')[:20000],
            'url': official_asset(assets[name]['browser_download_url']),
            'checksum_url': official_asset(assets[name + '.sha256']['browser_download_url']), 'name': name}


async def fetch_bytes(url, limit, target=None):
    allowed = {'github.com', 'api.github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}
    async with httpx.AsyncClient(timeout=30, headers={'User-Agent': 'LlamaPanel-Updater', 'Accept': 'application/vnd.github+json'}) as client:
        for _ in range(6):
            parsed = urlsplit(url)
            if parsed.scheme != 'https' or parsed.hostname not in allowed or parsed.username or parsed.port not in (None, 443):
                raise ValueError('Untrusted download redirect')
            async with client.stream('GET', url) as response:
                if response.is_redirect:
                    url = str(response.next_request.url)
                    continue
                response.raise_for_status()
                size = 0
                chunks = []
                stream = open(target, 'wb') if target else None
                try:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > limit:
                            raise ValueError('Download exceeds the allowed size')
                        if stream:
                            stream.write(chunk)
                        else:
                            chunks.append(chunk)
                finally:
                    if stream:
                        stream.close()
                return b''.join(chunks)
        raise ValueError('Too many download redirects')


def extract_release(archive: Path, destination: Path, expected_version: str):
    allowed_files = {'run.py', 'VERSION', 'README.md', 'LICENSE', 'settings.defaults.json', 'release.json'}
    seen = set()
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        if len(infos) > 20000 or sum(item.file_size for item in infos) > MAX_EXPANDED:
            raise ValueError('Release archive is too large')
        for item in infos:
            path = PurePosixPath(item.filename)
            parts = path.parts
            if (not parts or parts[0] != 'LlamaPanel' or '..' in parts or '\\' in item.filename
                    or ':' in item.filename or any(p.endswith((' ', '.')) for p in parts)
                    or stat.S_ISLNK(item.external_attr >> 16)):
                raise ValueError('Unsafe archive path')
            normalized = str(path).casefold()
            if normalized in seen:
                raise ValueError('Duplicate archive path')
            seen.add(normalized)
            relative = '/'.join(parts[1:])
            if item.is_dir():
                continue
            if relative not in allowed_files and not relative.startswith(('backend/app/', 'docs/', 'frontend/dist/')) and relative != 'backend/requirements.txt':
                raise ValueError(f'Unexpected release file: {relative}')
        # Validate every entry before writing any of them.
        bundle.extractall(destination)
    root = destination / 'LlamaPanel'
    required = ['run.py', 'VERSION', 'release.json', 'settings.defaults.json', 'backend/requirements.txt',
                'backend/app/main.py', 'backend/app/update_runtime.py', 'frontend/dist/index.html']
    if not all((root / path).is_file() for path in required):
        raise ValueError('Release is missing required files')
    if (root / 'VERSION').read_text().strip() != expected_version:
        raise ValueError('Archive version does not match the release')
    manifest = read_json(root / 'release.json')
    if manifest.get('updater_protocol') != PROTOCOL:
        raise ValueError('This release requires a newer updater; install it manually')
    if tuple(manifest.get('python_min', [3, 12])) > sys.version_info[:2]:
        raise ValueError('This release requires a newer Python installation')
    return root


class UpdateService:
    def __init__(self, app):
        self.app = app
        self.install = Path(os.environ.get('LLAMAPANEL_INSTALL_ROOT', ROOT))
        self.directory = self.install / '.updates'
        self.release = None
        self.task = None
        self.phase = 'idle'
        self.message = ''
        self.check_lock = asyncio.Lock()
        self.last_check = 0

    def unavailable_reason(self):
        if (self.install / '.git').exists():
            return 'In-app updates are available for release installations. Git checkouts are updated manually.'
        if not (self.install / 'release.json').is_file():
            return 'Install a release with updater support first.'
        if not os.environ.get('LLAMAPANEL_MANAGED') or not hasattr(self.app.state, 'request_restart'):
            return 'Start the release using python run.py to enable updates.'
        return None

    def status(self):
        disk = read_json(self.directory / 'status.json', {}) if not self.unavailable_reason() else {}
        phase = self.phase if self.task and not self.task.done() else disk.get('phase', self.phase)
        message = self.message if self.task and not self.task.done() else disk.get('message', self.message)
        return {'current_version': __version__, 'latest_version': self.release['version'] if self.release else None,
                'notes': self.release['notes'] if self.release else '', 'phase': phase, 'message': message,
                'supported': self.unavailable_reason() is None, 'reason': self.unavailable_reason(),
                'available': bool(self.release and version(self.release['version']) > version(__version__))}

    async def check(self):
        async with self.check_lock:
            if self.release and time.monotonic() - self.last_check < 60:
                return
            data = json.loads(await fetch_bytes(LATEST, 2 * 1024 * 1024))
            self.release = select_release(data)
            self.last_check = time.monotonic()

    def report(self, phase, message):
        self.phase, self.message = phase, message
        write_json(self.directory / 'status.json', {'phase': phase, 'message': message})

    def start(self, expected_version):
        if self.unavailable_reason():
            raise ValueError(self.unavailable_reason())
        if self.task and not self.task.done():
            raise ValueError('An update is already in progress')
        if not self.release or self.release['version'] != expected_version or version(expected_version) <= version(__version__):
            raise ValueError('Check for updates before installing a newer release')
        self.report('downloading', 'Downloading release…')
        self.task = asyncio.create_task(self.prepare(dict(self.release)))

    async def prepare(self, release):
        try:
            slot = uuid4().hex
            folder = self.directory / 'versions' / slot
            folder.mkdir(parents=True)
            archive = folder / 'release.zip'
            checksum = (await fetch_bytes(release['checksum_url'], 4096)).decode('ascii').strip().split()
            if len(checksum) != 2 or not re.fullmatch('[0-9a-fA-F]{64}', checksum[0]) or checksum[1].lstrip('*') != release['name']:
                raise ValueError('Invalid release checksum file')
            await fetch_bytes(release['url'], MAX_ARCHIVE, archive)
            with archive.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if actual != checksum[0].lower():
                raise ValueError('Release checksum does not match')
            self.report('preparing', 'Preparing the new version and its dependencies…')
            root = await asyncio.to_thread(extract_release, archive, folder, release['version'])
            await asyncio.to_thread(prepare_environment, root, folder / 'install.log')
            settings = self.app.state.settings
            # The supervisor snapshots JSON only after this worker's shutdown checkpoint.
            write_json(self.directory / 'request.json', {'slot': slot, 'version': release['version'],
                       'data_dir': str(settings.data_dir), 'host': settings.host, 'port': settings.port})
            self.report('restarting', 'Restarting the panel…')
            self.app.state.request_restart()
        except Exception as exc:
            (self.directory / 'request.json').unlink(missing_ok=True)
            self.report('failed', f'Update could not be installed: {exc}')

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
