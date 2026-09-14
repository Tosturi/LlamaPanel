import json
import urllib.error

from app import llama_client


class _FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self):
        return self._payload


def test_is_busy_true_when_any_slot_is_processing(monkeypatch):
    monkeypatch.setattr(
        llama_client.urllib.request, "urlopen",
        lambda url, timeout: _FakeResponse([{"is_processing": False}, {"is_processing": True}]),
    )
    assert llama_client.is_busy("127.0.0.1", 8080) is True


def test_is_busy_false_when_all_slots_idle(monkeypatch):
    monkeypatch.setattr(
        llama_client.urllib.request, "urlopen",
        lambda url, timeout: _FakeResponse([{"is_processing": False}]),
    )
    assert llama_client.is_busy("127.0.0.1", 8080) is False


def test_is_busy_false_when_no_slots(monkeypatch):
    monkeypatch.setattr(
        llama_client.urllib.request, "urlopen",
        lambda url, timeout: _FakeResponse([]),
    )
    assert llama_client.is_busy("127.0.0.1", 8080) is False


def test_is_busy_none_on_connection_error(monkeypatch):
    def raise_it(url, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(llama_client.urllib.request, "urlopen", raise_it)
    assert llama_client.is_busy("127.0.0.1", 8080) is None


def test_is_busy_none_on_malformed_response(monkeypatch):
    monkeypatch.setattr(
        llama_client.urllib.request, "urlopen",
        lambda url, timeout: _FakeResponse({"not": "a list"}),
    )
    assert llama_client.is_busy("127.0.0.1", 8080) is None


def test_is_busy_rewrites_wildcard_host_to_localhost(monkeypatch):
    seen = {}

    def fake_urlopen(url, timeout):
        seen["url"] = url
        return _FakeResponse([])

    monkeypatch.setattr(llama_client.urllib.request, "urlopen", fake_urlopen)
    llama_client.is_busy("0.0.0.0", 8080)

    assert seen["url"] == "http://127.0.0.1:8080/slots"
