import json

import httpx
import pytest

from app.llama_client import LlamaClient


def _client(handler) -> LlamaClient:
    """LlamaClient whose HTTP goes to `handler(request) -> Response` instead
    of the network."""
    return LlamaClient(transport=httpx.MockTransport(handler))


def _json(payload, status_code=200):
    return lambda request: httpx.Response(status_code, content=json.dumps(payload).encode())


def _raise(exc):
    def handler(request):
        raise exc
    return handler


# --- is_busy() -------------------------------------------------------------

async def test_is_busy_true_when_any_slot_is_processing():
    client = _client(_json([{"is_processing": False}, {"is_processing": True}]))
    assert await client.is_busy("127.0.0.1", 8080) is True


async def test_is_busy_false_when_all_slots_idle():
    client = _client(_json([{"is_processing": False}]))
    assert await client.is_busy("127.0.0.1", 8080) is False


async def test_is_busy_false_when_no_slots():
    client = _client(_json([]))
    assert await client.is_busy("127.0.0.1", 8080) is False


async def test_is_busy_none_on_connection_error():
    client = _client(_raise(httpx.ConnectError("connection refused")))
    assert await client.is_busy("127.0.0.1", 8080) is None


async def test_is_busy_none_when_slots_endpoint_disabled():
    # llama-server started with --no-slots answers 501.
    client = _client(_json({"error": "disabled"}, status_code=501))
    assert await client.is_busy("127.0.0.1", 8080) is None


async def test_is_busy_none_on_malformed_response():
    client = _client(_json({"not": "a list"}))
    assert await client.is_busy("127.0.0.1", 8080) is None


@pytest.mark.parametrize("wildcard", ["0.0.0.0", "::"])
async def test_is_busy_rewrites_wildcard_host_to_localhost(wildcard):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, content=b"[]")

    await _client(handler).is_busy(wildcard, 8080)
    assert seen["url"] == "http://127.0.0.1:8080/slots"


# --- is_healthy() ----------------------------------------------------------

async def test_is_healthy_true_on_200():
    client = _client(_json({"status": "ok"}))
    assert await client.is_healthy("127.0.0.1", 8080) is True


async def test_is_healthy_false_while_model_is_loading():
    client = _client(_json({"error": {"message": "Loading model"}}, status_code=503))
    assert await client.is_healthy("127.0.0.1", 8080) is False


async def test_is_healthy_none_when_unreachable():
    client = _client(_raise(httpx.ConnectError("connection refused")))
    assert await client.is_healthy("127.0.0.1", 8080) is None


async def test_is_healthy_none_on_unexpected_status():
    client = _client(_json({}, status_code=404))
    assert await client.is_healthy("127.0.0.1", 8080) is None


async def test_is_healthy_hits_the_health_endpoint():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200)

    await _client(handler).is_healthy("10.0.0.5", 9001)
    assert seen["url"] == "http://10.0.0.5:9001/health"
