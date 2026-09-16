import asyncio
import socket
import sys

import pytest

from app import process_manager as pm_module
from app.process_manager import ProcessManager

from tests.fakes import FakeLlamaClient


@pytest.fixture
def make_pm(settings):
    def _make(busy=None, healthy=None) -> ProcessManager:
        return ProcessManager(settings, FakeLlamaClient(busy=busy, healthy=healthy))
    return _make


# --- is_busy() -----------------------------------------------------------

async def test_is_busy_is_false_without_asking_llama_server_when_not_running(make_pm):
    pm = make_pm(busy=[True])
    pm._state = "stopped"
    assert await pm.is_busy() is False
    assert pm._client.calls == []


async def test_is_busy_is_false_while_starting(make_pm):
    pm = make_pm(busy=[True])
    pm._state = "starting"
    assert await pm.is_busy() is False


async def test_is_busy_queries_llama_client_with_the_running_flags_host_and_port(make_pm):
    pm = make_pm(busy=[True])
    pm._state = "running"
    pm._flags = {"host": "127.0.0.1", "port": 9001}

    assert await pm.is_busy() is True
    assert pm._client.calls == [("busy", "127.0.0.1", 9001)]


async def test_is_busy_falls_back_to_default_host_and_port_when_unset(make_pm):
    pm = make_pm(busy=[False])
    pm._state = "running"
    pm._flags = {}

    await pm.is_busy()
    assert pm._client.calls == [("busy", "127.0.0.1", 8080)]


# --- log tailer lifecycle --------------------------------------------------

async def test_starting_a_new_tail_cancels_the_previous_one(make_pm):
    pm = make_pm()
    pm._state = "running"

    pm._start_tail(start_at=0)
    first = pm._tail_task
    pm._start_tail(start_at=0)
    second = pm._tail_task

    await asyncio.sleep(0)  # let cancellation propagate
    assert first is not second
    assert first.cancelled()
    assert not second.done()

    pm._cancel_tail()
    await asyncio.sleep(0)
    assert second.cancelled()
    assert pm._tail_task is None


# --- start(): real "starting" state ---------------------------------------

def _sleep_forever_cmd() -> tuple[str, list[str]]:
    # A stand-in for llama-server: a process that stays alive until told to stop.
    return sys.executable, ["-c", "import time; time.sleep(60)"]


async def test_start_stays_starting_until_health_reports_ready(make_pm):
    pm = make_pm(healthy=[None, False, True])
    pm.READY_POLL_INTERVAL = 0.01
    binary, args = _sleep_forever_cmd()

    await pm.start(model_id="m", binary=binary, args=args, flags={"port": 9123})
    try:
        assert pm.state == "starting"
        assert pm._pid is not None

        await asyncio.wait_for(pm._ready_task, timeout=2)

        assert pm.state == "running"
        assert ("healthy", "127.0.0.1", 9123) in pm._client.calls
        assert "[llama-server is ready]" in pm._log_buffer
    finally:
        await pm.stop()

    assert pm.state == "stopped"
    assert pm._ready_task is None


async def test_stop_during_starting_cancels_the_readiness_poll(make_pm):
    pm = make_pm(healthy=[None])  # never becomes healthy
    pm.READY_POLL_INTERVAL = 0.01
    binary, args = _sleep_forever_cmd()

    await pm.start(model_id="m", binary=binary, args=args, flags={})
    ready = pm._ready_task
    assert pm.state == "starting"

    await pm.stop()
    await asyncio.sleep(0)

    assert pm.state == "stopped"
    assert ready.cancelled()


async def test_crash_while_starting_is_reported_as_crashed(make_pm):
    pm = make_pm(healthy=[None])
    pm.READY_POLL_INTERVAL = 0.01

    await pm.start(model_id="m", binary=sys.executable, args=["-c", "raise SystemExit(3)"], flags={})
    await asyncio.wait_for(pm._watch_task, timeout=5)
    await asyncio.sleep(0.05)  # let the readiness poll notice and exit

    assert pm.state == "crashed"
    assert pm._exit_code == 3
    assert pm._ready_task.done()


async def test_output_of_a_process_that_dies_instantly_still_reaches_the_log_buffer(make_pm, monkeypatch):
    # Regression: the tailer used to seek to the end of the log file when it
    # first ran, i.e. *after* the child was spawned. A child that fails and
    # exits within its first milliseconds (a native binary rejecting an
    # argument, say) had already written its error by then, so the UI showed
    # only "[process exited unexpectedly with code 1]" with nothing explaining
    # why. Python starts too slowly to lose that race naturally, so the
    # tailer is held back until the child is certainly gone.
    pm = make_pm(healthy=[None])
    pm.READY_POLL_INTERVAL = 0.01
    real_start_tail = pm._start_tail

    def start_tail_late(**kwargs):
        async def later():
            await asyncio.sleep(0.3)
            real_start_tail(**kwargs)
        pm._late = asyncio.create_task(later())

    monkeypatch.setattr(pm, "_start_tail", start_tail_late)
    code = "import sys; print('bind failed: address in use', flush=True); sys.exit(1)"

    await pm.start(model_id="m", binary=sys.executable, args=["-c", code], flags={})
    await asyncio.wait_for(pm._watch_task, timeout=5)
    await asyncio.sleep(0.8)  # tailer starts at 0.3s, then needs a poll tick

    assert pm.state == "crashed"
    assert "bind failed: address in use" in pm._log_buffer
    assert any("exited unexpectedly with code 1" in line for line in pm._log_buffer)


async def test_lines_written_before_start_are_not_replayed(make_pm):
    pm = make_pm(healthy=[None])
    pm.READY_POLL_INTERVAL = 0.01
    pm._settings.log_file.parent.mkdir(parents=True, exist_ok=True)
    pm._settings.log_file.write_text("stale line from a previous run\n", encoding="utf-8")

    await pm.start(model_id="m", binary=sys.executable, args=["-c", "raise SystemExit(0)"], flags={})
    await asyncio.wait_for(pm._watch_task, timeout=5)
    await asyncio.sleep(0.5)

    assert "stale line from a previous run" not in pm._log_buffer


async def test_start_resets_state_when_binary_is_missing(make_pm):
    pm = make_pm()
    with pytest.raises(FileNotFoundError):
        await pm.start(model_id="m", binary="definitely-not-a-real-binary-xyz", args=[], flags={})
    assert pm.state == "stopped"


async def test_shutdown_cancels_bookkeeping_tasks_but_leaves_process_alone(make_pm):
    pm = make_pm(healthy=[None])
    pm.READY_POLL_INTERVAL = 0.01
    binary, args = _sleep_forever_cmd()

    await pm.start(model_id="m", binary=binary, args=args, flags={})
    proc = pm._proc
    tasks = [pm._ready_task, pm._tail_task, pm._watch_task]

    await pm.shutdown()
    await asyncio.sleep(0)

    assert all(t.cancelled() for t in tasks)
    assert proc.returncode is None  # still running: the next panel adopts it
    proc.kill()
    await proc.wait()


# --- restart() -------------------------------------------------------------

async def test_restart_applies_immediately_when_idle(make_pm, monkeypatch):
    pm = make_pm()
    pm._state = "running"
    calls = []

    monkeypatch.setattr(pm, "is_busy", _async_return(False))
    monkeypatch.setattr(pm, "stop", _async_record(calls, "stop"))
    monkeypatch.setattr(pm, "_wait_for_port", _async_return(True))
    monkeypatch.setattr(pm, "start", _async_record(calls, "start"))

    result = await pm.restart(model_id="m", binary="llama-server", args=["--model", "m"], flags={"ctx_size": 8192})

    assert result == "applied"
    assert calls == ["stop", "start"]
    assert pm.restart_pending is False


async def test_restart_queues_when_busy_and_applies_once_idle(make_pm, monkeypatch):
    pm = make_pm()
    pm._state = "running"
    calls = []
    busy_sequence = iter([True, True, False])

    async def fake_is_busy():
        return next(busy_sequence)

    async def fast_sleep(_seconds):
        return None

    monkeypatch.setattr(pm, "is_busy", fake_is_busy)
    monkeypatch.setattr(pm, "stop", _async_record(calls, "stop"))
    monkeypatch.setattr(pm, "_wait_for_port", _async_return(True))
    monkeypatch.setattr(pm, "start", _async_record(calls, "start"))
    monkeypatch.setattr(pm_module.asyncio, "sleep", fast_sleep)

    result = await pm.restart(model_id="m", binary="llama-server", args=[], flags={})

    assert result == "queued"
    assert pm.restart_pending is True

    await pm._restart_task  # wait for the background poll loop to finish

    assert calls == ["stop", "start"]
    assert pm.restart_pending is False


async def test_cancel_restart_clears_pending_state_and_never_restarts(make_pm, monkeypatch):
    pm = make_pm()
    pm._state = "running"
    calls = []

    async def always_busy():
        return True

    real_sleep = asyncio.sleep

    async def short_sleep(_seconds):
        await real_sleep(0.01)

    monkeypatch.setattr(pm, "is_busy", always_busy)
    monkeypatch.setattr(pm, "stop", _async_record(calls, "stop"))
    monkeypatch.setattr(pm, "_wait_for_port", _async_return(True))
    monkeypatch.setattr(pm, "start", _async_record(calls, "start"))
    monkeypatch.setattr(pm_module.asyncio, "sleep", short_sleep)

    result = await pm.restart(model_id="m", binary="b", args=[], flags={})
    assert result == "queued"

    await asyncio.sleep(0.03)  # let the background loop poll at least once
    await pm.cancel_restart()

    assert pm.restart_pending is False
    assert calls == []
    assert pm._restart_task is None


# --- restart robustness: port wait + one retry ------------------------------

def _hold_port() -> tuple[socket.socket, int]:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen()
    return s, s.getsockname()[1]


def test_port_is_free_reflects_a_live_listener():
    held, port = _hold_port()
    try:
        assert pm_module._port_is_free("127.0.0.1", port) is False
    finally:
        held.close()
    assert pm_module._port_is_free("127.0.0.1", port) is True


async def test_wait_for_port_returns_once_the_previous_listener_is_gone(make_pm):
    pm = make_pm()
    pm.PORT_POLL_INTERVAL = 0.01
    held, port = _hold_port()

    async def release_soon():
        await asyncio.sleep(0.15)
        held.close()

    asyncio.create_task(release_soon())
    freed = await asyncio.wait_for(pm._wait_for_port({"port": port}), timeout=3)

    assert freed is True
    assert any("waiting for port" in line for line in pm._log_buffer)
    assert f"[port {port} is free again]" in pm._log_buffer


async def test_wait_for_port_gives_up_after_timeout_and_says_so(make_pm):
    pm = make_pm()
    pm.PORT_POLL_INTERVAL = 0.01
    pm.PORT_WAIT_TIMEOUT = 0.1
    held, port = _hold_port()
    try:
        freed = await pm._wait_for_port({"host": "127.0.0.1", "port": port})
    finally:
        held.close()

    assert freed is False
    assert any("starting anyway" in line for line in pm._log_buffer)


async def test_wait_for_port_is_immediate_when_nothing_listens(make_pm):
    pm = make_pm()
    held, port = _hold_port()
    held.close()

    assert await pm._wait_for_port({"port": port}) is True
    assert not any("port" in line for line in pm._log_buffer)


class _FakeProc:
    """Stands in for asyncio.subprocess.Process: exits when told to."""

    def __init__(self):
        self._exited = asyncio.Event()
        self.returncode = None

    def exit(self, code: int):
        self.returncode = code
        self._exited.set()

    async def wait(self):
        await self._exited.wait()
        return self.returncode


async def test_early_death_after_restart_is_retried_once(make_pm, monkeypatch):
    pm = make_pm()
    pm.RETRY_DELAY = 0.01
    calls = []
    proc = _FakeProc()
    pm._proc = proc
    pm._state = "starting"
    monkeypatch.setattr(pm, "_wait_for_port", _async_return(True))
    monkeypatch.setattr(pm, "start", _async_record(calls, "start"))
    pending = {"model_id": "m", "binary": "b", "args": [], "flags": {}}

    task = asyncio.create_task(pm._retry_if_dies_early(pending, proc))
    await asyncio.sleep(0.02)
    pm._state = "crashed"  # what _watch_exit records
    proc.exit(1)
    await asyncio.wait_for(task, timeout=2)

    assert calls == ["start"]
    assert any("retrying once" in line for line in pm._log_buffer)


async def test_no_retry_when_the_process_was_stopped_on_purpose(make_pm, monkeypatch):
    pm = make_pm()
    pm.RETRY_DELAY = 0.01
    calls = []
    proc = _FakeProc()
    pm._proc = proc
    monkeypatch.setattr(pm, "start", _async_record(calls, "start"))

    task = asyncio.create_task(pm._retry_if_dies_early({"flags": {}}, proc))
    await asyncio.sleep(0.02)
    pm._state = "stopped"
    proc.exit(1)
    await asyncio.wait_for(task, timeout=2)

    assert calls == []


async def test_no_retry_when_the_process_outlives_the_early_exit_window(make_pm, monkeypatch):
    pm = make_pm()
    pm.EARLY_EXIT_WINDOW = 0.05
    calls = []
    proc = _FakeProc()
    pm._proc = proc
    pm._state = "running"
    monkeypatch.setattr(pm, "start", _async_record(calls, "start"))

    await asyncio.wait_for(pm._retry_if_dies_early({"flags": {}}, proc), timeout=2)
    pm._state = "crashed"
    proc.exit(1)  # dies later - that's a real crash, not a restart race
    await asyncio.sleep(0.02)

    assert calls == []


async def test_stop_and_start_retries_a_real_process_exactly_once(make_pm, monkeypatch):
    pm = make_pm(healthy=[None])
    pm.READY_POLL_INTERVAL = 0.01
    pm.RETRY_DELAY = 0.05
    starts = []
    real_start = pm.start

    async def counting_start(**kwargs):
        starts.append(kwargs["model_id"])
        await real_start(**kwargs)

    monkeypatch.setattr(pm, "start", counting_start)
    monkeypatch.setattr(pm, "_wait_for_port", _async_return(True))
    pending = {"model_id": "m", "binary": sys.executable, "args": ["-c", "raise SystemExit(1)"], "flags": {}}

    await pm._stop_and_start(pending)
    await asyncio.wait_for(pm._retry_task, timeout=5)
    await asyncio.wait_for(pm._watch_task, timeout=5)

    assert starts == ["m", "m"]
    assert pm.state == "crashed"
    assert sum("retrying once" in line for line in pm._log_buffer) == 1


async def test_stop_cancels_a_pending_retry(make_pm, monkeypatch):
    pm = make_pm(healthy=[None])
    pm.READY_POLL_INTERVAL = 0.01
    binary, args = _sleep_forever_cmd()
    monkeypatch.setattr(pm, "_wait_for_port", _async_return(True))

    await pm._stop_and_start({"model_id": "m", "binary": binary, "args": args, "flags": {}})
    retry = pm._retry_task
    assert retry is not None and not retry.done()

    await pm.stop()
    await asyncio.sleep(0)

    assert retry.cancelled()
    assert pm._retry_task is None
    assert pm.state == "stopped"


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value
    return _inner


def _async_record(calls: list, label: str):
    async def _inner(*args, **kwargs):
        calls.append(label)
    return _inner
