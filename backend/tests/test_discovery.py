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
    """Mimics what discovery uses of psutil.Process: the pre-fetched `info`
    dict from process_iter(attrs) and an on-demand cmdline() call. Counts
    cmdline() calls so tests can assert argv is only read for candidates."""

    def __init__(self, pid, cmdline, name=None):
        self.info = {"pid": pid, "name": name if name is not None else cmdline[0]}
        self._cmdline = cmdline
        self.cmdline_calls = 0

    def cmdline(self):
        self.cmdline_calls += 1
        return self._cmdline


def _install(monkeypatch, *procs):
    seen_attrs = []

    def fake_iter(attrs):
        seen_attrs.append(list(attrs))
        return iter(procs)

    monkeypatch.setattr(discovery.psutil, "process_iter", fake_iter)
    return seen_attrs


def test_find_running_llama_server_parses_model_and_flags(monkeypatch):
    cmdline = [
        "llama-server", "--model", "/models/foo.gguf",
        "--ctx-size", "8192", "--no-kv-offload", "--flash-attn", "auto",
    ]
    _install(monkeypatch, _FakeProcess(pid=123, cmdline=cmdline))

    found = discovery.find_running_llama_server("llama-server")

    assert found is not None
    assert found["pid"] == 123
    assert found["model_path"] == "/models/foo.gguf"
    assert found["flags"]["ctx_size"] == 8192
    assert found["flags"]["no_kv_offload"] is True
    assert found["flags"]["flash_attn"] == "auto"


def test_find_running_llama_server_returns_none_when_no_match(monkeypatch):
    _install(monkeypatch, _FakeProcess(pid=1, cmdline=["python", "other.py"]))

    assert discovery.find_running_llama_server("llama-server") is None


def test_find_running_llama_server_skips_processes_it_cannot_inspect(monkeypatch):
    class _RaisingProcess:
        @property
        def info(self):
            raise psutil.NoSuchProcess(pid=1)

    good = _FakeProcess(pid=2, cmdline=["llama-server", "--model", "/m.gguf"])
    _install(monkeypatch, _RaisingProcess(), good)

    found = discovery.find_running_llama_server("llama-server")
    assert found["pid"] == 2


def test_argv_is_only_read_for_processes_whose_name_matches(monkeypatch):
    others = [_FakeProcess(pid=i, cmdline=[f"proc{i}.exe"]) for i in range(50)]
    target = _FakeProcess(pid=99, cmdline=["llama-server", "--model", "/m.gguf"])
    seen_attrs = _install(monkeypatch, *others, target)

    found = discovery.find_running_llama_server("llama-server")

    assert found["pid"] == 99
    assert seen_attrs == [["pid", "name"]]  # cmdline must not be bulk-fetched
    assert all(p.cmdline_calls == 0 for p in others)
    assert target.cmdline_calls == 1


def test_binary_is_matched_regardless_of_path_extension_and_case(monkeypatch):
    proc = _FakeProcess(
        pid=7,
        name="Llama-Server.exe",
        cmdline=["C:\\llama\\Llama-Server.exe", "--model", "C:\\m\\x.gguf"],
    )
    _install(monkeypatch, proc)

    assert discovery.find_running_llama_server("llama-server")["pid"] == 7
    assert discovery.find_running_llama_server("D:\\other\\llama-server.exe")["pid"] == 7
    assert discovery.find_running_llama_server("llama-cli") is None


def test_process_that_vanishes_between_snapshot_and_cmdline_is_skipped(monkeypatch):
    class _Gone(_FakeProcess):
        def cmdline(self):
            raise psutil.NoSuchProcess(pid=self.info["pid"])

    gone = _Gone(pid=1, cmdline=["llama-server"])
    alive = _FakeProcess(pid=2, cmdline=["llama-server", "--model", "/m.gguf"])
    _install(monkeypatch, gone, alive)

    assert discovery.find_running_llama_server("llama-server")["pid"] == 2
