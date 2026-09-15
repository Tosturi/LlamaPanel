import asyncio

import pytest

from app import process_manager as pm_module
from app.process_manager import ProcessManager


# --- is_busy() -----------------------------------------------------------

async def test_is_busy_is_false_without_checking_llama_server_when_not_running():
    pm = ProcessManager()
    pm._state = "stopped"
    assert await pm.is_busy() is False


async def test_is_busy_queries_llama_client_with_the_running_flags_host_and_port(monkeypatch):
    pm = ProcessManager()
    pm._state = "running"
    pm._flags = {"host": "127.0.0.1", "port": 9001}
    seen = {}

    def fake_is_busy(host, port):
        seen["host"] = host
        seen["port"] = port
        return True

    monkeypatch.setattr(pm_module.llama_client, "is_busy", fake_is_busy)

    assert await pm.is_busy() is True
    assert seen == {"host": "127.0.0.1", "port": 9001}


async def test_is_busy_falls_back_to_default_host_and_port_when_unset(monkeypatch):
    pm = ProcessManager()
    pm._state = "running"
    pm._flags = {}
    seen = {}

    def fake_is_busy(host, port):
        seen["host"] = host
        seen["port"] = port
        return False

    monkeypatch.setattr(pm_module.llama_client, "is_busy", fake_is_busy)

    await pm.is_busy()
    assert seen == {"host": "127.0.0.1", "port": 8080}


# --- log tailer lifecycle --------------------------------------------------

async def test_starting_a_new_tail_cancels_the_previous_one():
    pm = ProcessManager()
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


# --- restart() -------------------------------------------------------------

async def test_restart_applies_immediately_when_idle(monkeypatch):
    pm = ProcessManager()
    pm._state = "running"
    calls = []

    monkeypatch.setattr(pm, "is_busy", _async_return(False))
    monkeypatch.setattr(pm, "stop", _async_record(calls, "stop"))
    monkeypatch.setattr(pm, "start", _async_record(calls, "start"))

    result = await pm.restart(model_id="m", binary="llama-server", args=["--model", "m"], flags={"ctx_size": 8192})

    assert result == "applied"
    assert calls == ["stop", "start"]
    assert pm.restart_pending is False


async def test_restart_queues_when_busy_and_applies_once_idle(monkeypatch):
    pm = ProcessManager()
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


async def test_cancel_restart_clears_pending_state_and_never_restarts(monkeypatch):
    pm = ProcessManager()
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


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value
    return _inner


def _async_record(calls: list, label: str):
    async def _inner(*args, **kwargs):
        calls.append(label)
    return _inner
