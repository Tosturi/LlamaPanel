"""Run only in the optional harness venv. Harness owns tasks and scoring."""

import hashlib
import json
import random
import sqlite3
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def event(**data):
    print("LLAMAPANEL_EVENT " + json.dumps(data, ensure_ascii=False), flush=True)


def dump(path, data):
    from lm_eval.utils import handle_non_serializable

    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, default=handle_non_serializable),
        encoding="utf-8",
    )
    temporary.replace(path)


class ResourceFailure(RuntimeError):
    pass


def run(config, directory):
    import requests
    from lm_eval import evaluator
    from lm_eval.models.gguf import GGUFLM
    from lm_eval.tasks import TaskManager, get_task_dict

    task_name = config["task"]
    manager = TaskManager()
    tasks = get_task_dict([task_name], task_manager=manager)
    if list(tasks) != [task_name]:
        raise ValueError("Select a single supported task, not a group")
    task = tasks[task_name]
    if task.OUTPUT_TYPE not in (
        "generate_until",
        "multiple_choice",
        "loglikelihood",
    ) or getattr(task, "UNSAFE_CODE", False):
        raise ValueError("Task requires an unsupported evaluation capability")
    docs = task.eval_docs
    indices = list(range(len(docs)))
    if config.get("limit") and config["limit"] < len(indices):
        indices = sorted(random.Random(config["seed"]).sample(indices, config["limit"]))
    fingerprint = {
        "splits": {k: v._fingerprint for k, v in task.dataset.items()},
        "indices": indices,
        "config": task.dump_config(),
    }
    # Compare all splits (including few-shot sources) before any model requests.
    manifest_path = Path(config["manifest"])
    normalized = json.loads(json.dumps(fingerprint, default=str))
    if manifest_path.exists():
        if json.loads(manifest_path.read_text(encoding="utf-8")) != normalized:
            raise ValueError(
                "Task data/config changed between participants; start a new comparison"
            )
    else:
        dump(manifest_path, normalized)
    if config.get("prepare"):
        event(prepared=len(indices), task=task_name)
        return

    control = Path(config["control"])
    participant = config["participant"]
    concurrency = participant["effective_concurrency"]
    session = requests.Session()
    session.trust_env = False
    props_response = session.get(config["url"] + "/props", timeout=15)
    props_response.raise_for_status()
    props = props_response.json()
    actual_context = props.get("default_generation_settings", {}).get("n_ctx")
    if not isinstance(actual_context, int) or actual_context < config["max_length"]:
        raise ValueError(
            f"Server context per slot is {actual_context}; requires {config['max_length']}. Increase Context size or reduce Concurrent requests."
        )
    if props.get("total_slots", 0) < concurrency:
        raise ValueError("Server exposes fewer slots than requested")
    dump(directory / "server-props.json", props)

    class PanelGGUF(GGUFLM):
        def __init__(self):
            super().__init__(
                base_url=config["url"],
                parallel=concurrency,
                max_length=config["max_length"],
                max_gen_toks=participant["max_tokens"],
                temperature=participant["temperature"],
                timeout=config["timeout"],
            )
            self.cache = sqlite3.connect(
                directory / "responses.sqlite", check_same_thread=False
            )
            self.cache.execute(
                "CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, value TEXT)"
            )
            self.cache_lock = threading.Lock()
            self.slot_locks = [threading.Lock() for _ in range(concurrency)]

        @property
        def tokenizer_name(self):
            return "llama-server"

        def chat_template(self, chat_template=False):
            return props.get("chat_template", "") if chat_template else ""

        def apply_chat_template(self, chat_history, add_generation_prompt=True):
            return self._post_with_retries(
                self.server_url + "/apply-template",
                {
                    "messages": chat_history,
                    "add_generation_prompt": add_generation_prompt,
                },
            )["prompt"]

        def _post_with_retries(self, url, payload, **kwargs):
            payload = dict(payload)
            if url.endswith("/v1/completions"):
                payload.update(seed=config["seed"], cache_prompt=True)
                prompt = payload["prompt"]
                tokens = (
                    prompt
                    if isinstance(prompt, list)
                    else self._tokenize(prompt, add_special=True)
                )
                if len(tokens) + payload.get("max_tokens", 1) > self.max_length:
                    raise ValueError(
                        "Prompt plus requested output exceeds Max sequence length; no truncation was applied"
                    )
            try:
                response = session.post(url, json=payload, timeout=self.timeout)
            except requests.RequestException as exc:
                raise ResourceFailure(str(exc)) from exc
            if response.status_code >= 400:
                text = response.text[:2000]
                if response.status_code in (500, 503) or any(
                    s in text.lower()
                    for s in ("out of memory", "cuda error", "allocation failed")
                ):
                    raise ResourceFailure(text)
                raise ValueError(f"llama-server HTTP {response.status_code}: {text}")
            data = response.json()
            if data.get("truncated"):
                raise ValueError("Server truncated an evaluation prompt")
            return data

        def _loglikelihood_one(self, item):
            # Upstream assigns equal-context candidates to one slot. Serialize
            # that slot to avoid concurrently reusing its KV state.
            with self.slot_locks[item[1]]:
                return super()._loglikelihood_one(item)

        def _map_requests(self, fn, items, disable_tqdm):
            results = [None] * len(items)
            work = list(enumerate(items))
            if fn.__name__ == "_loglikelihood_one":
                # Interleave slots so a batch contains different questions,
                # rather than serializing every choice on a single slot.
                positions = {}
                ordered = []
                for index, item in work:
                    slot = item[1]
                    rank = positions.get(slot, 0)
                    positions[slot] = rank + 1
                    ordered.append((rank, slot, index, item))
                work = [(index, item) for _, _, index, item in sorted(ordered)]

            def cached(entry):
                index, item = entry
                args = item[0] if fn.__name__ == "_loglikelihood_one" else item
                key = hashlib.sha256(
                    json.dumps([fn.__name__, args], sort_keys=True).encode()
                ).hexdigest()
                with self.cache_lock:
                    value = self.cache.execute(
                        "SELECT value FROM responses WHERE key=?", (key,)
                    ).fetchone()
                if value:
                    result = json.loads(value[0])
                    return index, (
                        tuple(result) if fn.__name__ == "_loglikelihood_one" else result
                    )
                result = fn(item)
                if result is None:
                    raise ValueError("Server returned no evaluation result")
                with self.cache_lock:
                    self.cache.execute(
                        "INSERT OR REPLACE INTO responses VALUES (?, ?)",
                        (key, json.dumps(result)),
                    )
                    self.cache.commit()
                return index, result

            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                for offset in range(0, len(items), concurrency):
                    notified = False
                    while control.exists():
                        if not notified:
                            event(paused=True)
                            notified = True
                        time.sleep(0.2)
                    for index, result in pool.map(
                        cached, work[offset : offset + concurrency]
                    ):
                        results[index] = result
                    event(
                        requests_completed=min(offset + concurrency, len(items)),
                        requests_total=len(items),
                    )
            return results

    lm = PanelGGUF()
    if config["chat_template"]:
        if not props.get("chat_template"):
            raise ValueError("Selected runtime does not expose a chat template")
        lm.apply_chat_template([{"role": "user", "content": "test"}])
    if task.OUTPUT_TYPE != "generate_until":
        ids = lm._tokenize("test", add_special=True)
        if not ids:
            raise ValueError("Server tokenizer returned no tokens")
        lm._score_position(ids, ids[-1], id_slot=0)
    results = evaluator.simple_evaluate(
        model=lm,
        tasks=[task],
        task_manager=manager,
        num_fewshot=config["num_fewshot"],
        samples={task_name: indices},
        log_samples=True,
        bootstrap_iters=1000,
        apply_chat_template=config["chat_template"],
        gen_kwargs={
            "max_gen_toks": participant["max_tokens"],
            "temperature": participant["temperature"],
            "do_sample": participant["temperature"] > 0,
        },
        random_seed=config["seed"],
        numpy_random_seed=config["seed"],
        torch_random_seed=config["seed"],
        fewshot_random_seed=config["seed"],
    )
    if not results:
        raise ValueError("Harness returned no results")
    dump(directory / "results.json", results)
    lm.cache.close()
    event(finished=True)


if __name__ == "__main__":
    if sys.argv[1] == "--check":
        from lm_eval import evaluator
        from lm_eval.models.gguf import GGUFLM

        assert hasattr(GGUFLM, "_score_position") and hasattr(GGUFLM, "_map_requests")
        sys.exit(0)
    path = Path(sys.argv[1])
    try:
        run(json.loads(path.read_text(encoding="utf-8")), path.parent)
    except Exception as exc:
        traceback.print_exc()
        dump(
            path.parent / "error.json",
            {"message": str(exc), "resource": isinstance(exc, ResourceFailure)},
        )
        sys.exit(1)
