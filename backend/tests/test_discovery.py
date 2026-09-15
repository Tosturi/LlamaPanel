import psutil

from app import discovery


def test_coerce_number_parses_int():
    assert discovery._coerce("number", "4096") == 4096


def test_coerce_number_parses_float_when_not_int():
    assert discovery._coerce("number", "1.5") == 1.5


def test_coerce_number_falls_back_to_raw_string_on_garbage():
    assert discovery._coerce("number", "auto") == "auto"


def test_coerce_non_number_returns_raw_unchanged():
    assert discovery._coerce("string", "auto") == "auto"


class _FakeProcess:
    def __init__(self, pid, cmdline):
        self.info = {"pid": pid, "cmdline": cmdline}


def test_find_running_llama_server_parses_model_and_flags(monkeypatch):
    cmdline = [
        "llama-server", "--model", "/models/foo.gguf",
        "--ctx-size", "8192", "--no-kv-offload", "--flash-attn", "auto",
    ]
    fake_proc = _FakeProcess(pid=123, cmdline=cmdline)
    monkeypatch.setattr(discovery.psutil, "process_iter", lambda attrs: iter([fake_proc]))

    found = discovery.find_running_llama_server("llama-server")

    assert found is not None
    assert found["pid"] == 123
    assert found["model_path"] == "/models/foo.gguf"
    assert found["flags"]["ctx_size"] == 8192
    assert found["flags"]["no_kv_offload"] is True
    assert found["flags"]["flash_attn"] == "auto"


def test_find_running_llama_server_returns_none_when_no_match(monkeypatch):
    fake_proc = _FakeProcess(pid=1, cmdline=["python", "other.py"])
    monkeypatch.setattr(discovery.psutil, "process_iter", lambda attrs: iter([fake_proc]))

    assert discovery.find_running_llama_server("llama-server") is None


def test_find_running_llama_server_skips_processes_it_cannot_inspect(monkeypatch):
    class _RaisingProcess:
        @property
        def info(self):
            raise psutil.NoSuchProcess(pid=1)

    good = _FakeProcess(pid=2, cmdline=["llama-server", "--model", "/m.gguf"])
    monkeypatch.setattr(
        discovery.psutil, "process_iter", lambda attrs: iter([_RaisingProcess(), good])
    )

    found = discovery.find_running_llama_server("llama-server")
    assert found["pid"] == 2
