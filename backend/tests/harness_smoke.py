"""Offline contract test with the real pinned harness and a fake llama-server.

Run using the optional harness Python; no models, HF access or GPU are needed.
"""

import importlib.util
import json
import sqlite3
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from datasets import Dataset, DatasetDict
from lm_eval.api.task import ConfigurableTask
from lm_eval.tasks import TaskManager

worker_path = Path(__file__).parents[1] / "app/evals/harness_worker.py"
spec = importlib.util.spec_from_file_location("worker", worker_path)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def checked_run(config, directory):
    connections = []
    connect = sqlite3.connect

    def tracked_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection

    try:
        with patch.object(worker.sqlite3, "connect", side_effect=tracked_connect):
            return worker.run(config, directory)
    finally:
        # Retain references so GC cannot hide a leaked handle on Linux.
        for connection in connections:
            try:
                connection.execute("SELECT 1")
            except sqlite3.ProgrammingError:
                continue
            raise AssertionError("Worker left its response cache open")


class TinyTask(ConfigurableTask):
    def download(self, *args, **kwargs):
        self.dataset = DatasetDict(
            test=Dataset.from_list(
                [
                    {
                        "question": "Q1",
                        "answer": "yes",
                        "choices": ["yes", "no"],
                        "gold": 0,
                    },
                    {
                        "question": "Q2",
                        "answer": "yes",
                        "choices": ["yes", "no"],
                        "gold": 0,
                    },
                    {
                        "question": "Q3",
                        "answer": "yes",
                        "choices": ["yes", "no"],
                        "gold": 0,
                    },
                ]
            )
        )


def task(kind):
    config = dict(
        task="tiny",
        test_split="test",
        doc_to_text="question",
        doc_to_target="answer",
        num_fewshot=0,
        output_type=kind,
    )
    if kind == "generate_until":
        config.update(
            metric_list=[
                dict(metric="exact_match", aggregation="mean", higher_is_better=True)
            ],
            generation_kwargs=dict(until=["STOP"], max_gen_toks=8, do_sample=False),
        )
    else:
        config.update(doc_to_target="gold", doc_to_choice="choices")
    return TinyTask(config=config)


class Server(BaseHTTPRequestHandler):
    calls = []
    failed = False
    fail_next = False
    context = 4096

    def log_message(self, *args):
        pass

    def respond(self, data, code=200):
        raw = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self.respond(
            dict(
                total_slots=2,
                default_generation_settings={"n_ctx": self.context},
                chat_template="test template",
            )
        )

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.calls.append((self.path, data))
        if self.path == "/tokenize":
            self.respond(
                {
                    "tokens": ([1] if data.get("add_special") else [])
                    + list(data["content"].encode())
                }
            )
        elif self.path == "/apply-template":
            self.respond({"prompt": "\n".join(m["content"] for m in data["messages"])})
        elif self.path == "/v1/completions":
            if self.fail_next:
                type(self).fail_next = False
                self.respond({"error": "out of memory"}, 500)
                return
            if "logit_bias" in data:
                token = data["logit_bias"][0][0]
                self.respond(
                    {
                        "choices": [
                            {
                                "logprobs": {
                                    "content": [
                                        {
                                            "id": token,
                                            "logprob": -0.1,
                                            "top_logprobs": [
                                                {"id": token, "logprob": -0.1}
                                            ],
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                )
            else:
                self.respond({"choices": [{"text": "yes", "finish_reason": "stop"}]})
        else:
            self.respond({"error": "unknown"}, 404)


def main():
    manager = TaskManager()
    patch("lm_eval.tasks.TaskManager", return_value=manager).start()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            for kind in ("generate_until", "multiple_choice"):
                directory = root / kind
                directory.mkdir()
                config = dict(
                    task="tiny",
                    seed=42,
                    limit=2,
                    manifest=str(directory / "manifest.json"),
                    control=str(directory / "pause"),
                    participant={
                        "effective_concurrency": 2,
                        "max_tokens": 8,
                        "temperature": 0,
                    },
                    url=f"http://127.0.0.1:{server.server_port}",
                    max_length=4096,
                    timeout=5,
                    chat_template=False,
                    num_fewshot=0,
                )
                with patch(
                    "lm_eval.tasks.get_task_dict",
                    side_effect=lambda *a, **kw: {"tiny": task(kind)},
                ):
                    checked_run({**config, "prepare": True}, directory)
                    checked_run(config, directory)
                    result = json.loads((directory / "results.json").read_text())
                    assert len(result["samples"]["tiny"]) == 2
                    metric = (
                        "exact_match,none" if kind == "generate_until" else "acc,none"
                    )
                    assert result["results"]["tiny"][metric] == (
                        1 if kind == "generate_until" else 0
                    ), result["results"]
                    if kind != "generate_until":
                        assert result["results"]["tiny"]["acc_norm,none"] == 1
                    before = len([c for c in Server.calls if c[0] == "/v1/completions"])
                    checked_run(config, directory)
                    after = len([c for c in Server.calls if c[0] == "/v1/completions"])
                    # The likelihood capability probe is intentionally repeated.
                    assert after - before == (0 if kind == "generate_until" else 1)
                    manifest = json.loads((directory / "manifest.json").read_text())
                    manifest["indices"] = [999]
                    (directory / "manifest.json").write_text(json.dumps(manifest))
                    try:
                        checked_run(config, directory)
                        raise AssertionError("Changed dataset accepted")
                    except ValueError as exc:
                        assert "changed between participants" in str(exc)
            directory = root / "limits"
            directory.mkdir()
            config.update(
                manifest=str(directory / "manifest.json"),
                control=str(directory / "pause"),
            )
            with patch(
                "lm_eval.tasks.get_task_dict",
                side_effect=lambda *a, **kw: {"tiny": task("generate_until")},
            ):
                Server.context = 1024
                try:
                    checked_run(config, directory)
                    raise AssertionError("Insufficient context accepted")
                except ValueError as exc:
                    assert "context per slot" in str(exc)
                Server.context = 4096
                Server.fail_next = True
                try:
                    checked_run(config, directory)
                    raise AssertionError("OOM swallowed")
                except worker.ResourceFailure:
                    pass
                checked_run(config, directory)
                config["chat_template"] = True
                # A different prompt produces a different response-cache key.
                checked_run(config, directory)
                assert any(p == "/apply-template" for p, _ in Server.calls)
            print(
                "Real harness integration passed: generation, likelihood, response reuse, dataset guard, context guard, resource recovery, chat template."
            )
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
