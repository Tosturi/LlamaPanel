import asyncio
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

    pm._start_tail(from_start=False)
    first = pm._tail_task
    pm._start_tail(from_start=False)
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
    monkeypatch.setattr(pm, "start", _async_record(calls, "start"))
    monkeypatch.setattr(pm_module.asyncio, "sleep", short_sleep)

    result = await pm.restart(model_id="m", binary="b", args=[], flags={})
    assert result == "queued"

    await asyncio.sleep(0.03)  # let the background loop poll at least once
    await pm.cancel_restart()

    assert pm.restart_pending is False
    assert calls == []
    assert pm._restart_task is None


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value
    return _inner


def _async_record(calls: list, label: str):
    async def _inner(*args, **kwargs):
        calls.append(label)
    return _inner
