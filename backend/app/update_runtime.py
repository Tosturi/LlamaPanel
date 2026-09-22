"""Standard-library release launcher. Keep protocol 1 compatible across releases.

The original installation is never overwritten. Each downloaded release keeps
its own venv at a permanent path; only the active-version pointer changes.
"""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from uuid import uuid4

PROTOCOL = 1
DATA_FILES = ('settings.json', 'presets.json', 'instances.json')


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path: Path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def release_root(install: Path, slot):
    if slot is None:
        return install
    if not isinstance(slot, str) or not re.fullmatch(r'[0-9a-f]{32}', slot):
        raise ValueError('Invalid release slot')
    return install / '.updates' / 'versions' / slot / 'LlamaPanel'


def python_in(root):
    return root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def ensure_environment(root: Path, log=None):
    python = python_in(root)
    if not python.exists():
        subprocess.run([sys.executable, '-m', 'venv', str(root / '.venv')],
                       check=True, timeout=180, stdout=log, stderr=log)
    requirements = root / 'backend' / 'requirements.txt'
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
    marker = root / '.venv' / 'requirements.sha256'
    if not marker.exists() or marker.read_text() != digest:
        subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(requirements)],
                       check=True, timeout=900, stdout=log, stderr=log)
        marker.write_text(digest)
    return python


@contextlib.contextmanager
def launcher_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            if stream.tell() == 0:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def snapshot(data_dir: Path, backup: Path):
    backup.mkdir(parents=True, exist_ok=False)
    present = []
    for name in DATA_FILES:
        if (data_dir / name).exists():
            shutil.copy2(data_dir / name, backup / name)
            present.append(name)
    write_json(backup / 'manifest.json', present)


def restore(data_dir: Path, backup: Path):
    present = read_json(backup / 'manifest.json')
    if not isinstance(present, list):
        raise ValueError('Update backup is incomplete; refusing automatic recovery')
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in DATA_FILES:
        target = data_dir / name
        if name in present:
            temporary = data_dir / (name + '.restore.tmp')
            shutil.copy2(backup / name, temporary)
            os.replace(temporary, target)
        elif target.exists():
            target.unlink()


def stop_worker(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def wait_ready(proc, host, port, token, version, timeout=45):
    host = '127.0.0.1' if host in ('0.0.0.0', '') else '::1' if host == '::' else host
    host = f'[{host}]' if ':' in host and not host.startswith('[') else host
    url = f'http://{host}:{port}/api/updates/ready'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and proc.poll() is None:
        try:
            with opener.open(url, timeout=1) as response:
                ready = json.load(response)
            if ready == {'token': token, 'version': version}:
                return True
        except (OSError, ValueError):
            pass
        time.sleep(.25)
    return False


def spawn(root, install, args, data_dir, token):
    write_json(install / '.updates' / 'worker-token.json', token)
    env = dict(os.environ, LLAMAPANEL_MANAGED='1', LLAMAPANEL_INSTALL_ROOT=str(install),
               LLAMAPANEL_DATA_DIR=str(data_dir), LLAMAPANEL_LAUNCH_TOKEN=token)
    return subprocess.Popen([str(python_in(root)), str(root / 'run.py'), *args], env=env)


def activate(install, state, request, args, spawn_fn=spawn, ready_fn=wait_ready):
    """Old worker has exited. Back up JSON before a candidate can migrate it."""
    updates = install / '.updates'
    root = release_root(install, request['slot'])
    data_dir = Path(request['data_dir'])
    backup = root.parent / 'data-backup'
    snapshot(data_dir, backup)
    journal = dict(request, previous=state.get('current'))
    write_json(updates / 'activation.json', journal)
    write_json(updates / 'status.json', {'phase': 'restarting', 'message': 'Starting the new version…'})
    proc = None
    try:
        token = uuid4().hex
        proc = spawn_fn(root, install, args, data_dir, token)
        if not ready_fn(proc, request['host'], request['port'], token, request['version']):
            raise RuntimeError('The new version did not become ready')
        next_state = {'current': request['slot'], 'previous': state.get('current')}
        write_json(updates / 'current.json', next_state)
        write_json(updates / 'status.json', {'phase': 'complete', 'message': f"Updated to {request['version']}."})
        (updates / 'activation.json').unlink()
    except BaseException:
        if proc is not None:
            stop_worker(proc)
        restore(data_dir, backup)
        write_json(updates / 'current.json', state)
        write_json(updates / 'status.json', {'phase': 'failed', 'message': 'Update failed to start. Previous version restored.'})
        (updates / 'activation.json').unlink(missing_ok=True)
        raise
    return proc, next_state


@contextlib.contextmanager
def worker_guard(install, token):
    with launcher_lock(install / '.updates' / 'worker.lock'):
        if read_json(install / '.updates' / 'worker-token.json') != token:
            raise RuntimeError('This panel launch has been superseded')
        yield


def recover(install):
    updates = install / '.updates'
    # A surviving worker must exit before restoring files. Invalidate pending
    # launches while holding the same lock acquired before worker startup.
    with launcher_lock(updates / 'worker.lock'):
        write_json(updates / 'worker-token.json', None)
        journal = read_json(updates / 'activation.json')
        if journal:
            root = release_root(install, journal['slot'])
            restore(Path(journal['data_dir']), root.parent / 'data-backup')
            write_json(updates / 'current.json', {'current': journal['previous']})
            (updates / 'activation.json').unlink()
            write_json(updates / 'status.json', {'phase': 'failed', 'message': 'Interrupted update rolled back.'})


def supervise(install: Path, args):
    from app.settings import default_data_dir
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--data-dir')
    options, _ = parser.parse_known_args(args)
    data_dir = Path(options.data_dir or os.environ.get('LLAMAPANEL_DATA_DIR') or default_data_dir()).expanduser().resolve()
    updates = install / '.updates'
    with launcher_lock(updates / 'launcher.lock'):
        recover(install)
        state = read_json(updates / 'current.json', {'current': None})
        (updates / 'request.json').unlink(missing_ok=True)
        status = read_json(updates / 'status.json', {})
        if status.get('phase') in ('downloading', 'preparing', 'restarting'):
            write_json(updates / 'status.json', {'phase': 'failed', 'message': 'Update interrupted; previous version kept.'})
        root = release_root(install, state.get('current'))
        ensure_environment(root)
        proc = spawn(root, install, args, data_dir, uuid4().hex)
        try:
            while True:
                code = proc.wait()
                request = read_json(updates / 'request.json')
                if not request:
                    return code
                (updates / 'request.json').unlink()
                if code != 0:
                    write_json(updates / 'status.json', {'phase': 'failed', 'message': 'Panel shutdown failed; update was not activated.'})
                else:
                    try:
                        proc, state = activate(install, state, request, args)
                        continue
                    except Exception as exc:
                        print(f'Update rolled back: {exc}', flush=True)
                        # Never start against partially restored data.
                        if (updates / 'activation.json').exists():
                            raise
                        write_json(updates / 'status.json', {'phase': 'failed', 'message': f'Previous version kept: {exc}'})
                proc = spawn(release_root(install, state.get('current')), install, args, data_dir, uuid4().hex)
        except KeyboardInterrupt:
            stop_worker(proc)
            return 0
