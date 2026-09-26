# Model evaluations

[Documentation](README.md)

Open **Evaluations** from Servers or a server workspace. Add participants using
saved presets, select each participant's runtime, choose installed benchmarks,
and run a comparison. A preset can reference a base GGUF, a different quantization,
or LoRA adapters. For before/after training, create separate presets first.

## Samples and results

**Full** runs the complete installed suite. **Custom** requires a positive number
of samples per benchmark. If a suite is smaller than that limit, all its samples
are used. A seeded selection is made once and reused for every participant.

Results include individual answers, conversations, errors, local-judge output,
and configuration snapshots. Accuracy is reported over successfully scored
samples; errors and the scored/total count are shown separately. Do not compare
scores without checking those counts. Truncated responses are errors, not silently
accepted answers. There is no aggregate quality score across unrelated tests.

## Benchmark library

Datasets are stored in `<data_dir>/benchmarks` by default. Use **Browse** or enter
an absolute directory to switch libraries. Existing files are not moved. The
library is shared by all comparisons. Downloads show progress and can be cancelled.
**Import JSON** validates a local suite; it never executes Python or other imported
code. Imports are limited to 32 MiB and 20,000 samples.

A content hash identifies each immutable installed revision; importing identical
content does not create another copy. Changed content becomes a new revision.
Deleting local dataset files does not delete past results or their input snapshots.
Dataset changes are blocked during evaluation or a download.

The initial catalog contains **GSM8K test**, with a pinned SHA-256 checksum and
MIT source attribution. It uses LlamaPanel's `llamapanel-gsm8k-zero-shot-v1` recipe:
chat completion, no few-shot examples, a step-by-step instruction, and a final
`#### <number>` delimiter. Numeric equality ignores commas and decimal formatting.
A missing final delimiter is incorrect. This is **not** the lm-evaluation-harness
leaderboard recipe; do not compare its scores directly with results using different
prompts, extraction rules, few-shot counts or model templates.

The first release supports text generation, exact/numeric scoring and fixed
multi-turn scripts with a local judge. It does not yet run loglikelihood tasks,
tool/environment agent benchmarks, arbitrary Hugging Face datasets, or harness /
Inspect tasks. Those need their own execution adapters, not just dataset files.

## Custom suites

Import a JSON file with this structure:

```json
{
  "name": "Memory check",
  "description": "Two-turn conversation",
  "scorer": "local_judge",
  "rubric": "Rate recall of the stated destination from 0 (forgotten) to 5 (correct and consistent). Explain your score.",
  "samples": [
    {
      "id": "destination-1",
      "system": "You are a guide at a railway station.",
      "turns": ["I am going to the northern station.", "Which station did I say I was going to?"],
      "answer": null
    }
  ]
}
```

`scorer` is `exact_match`, `numeric`, or `local_judge`. Exact match trims leading
and trailing whitespace, remains case-sensitive, and scores the final response.
Numeric scoring uses the final delimiter described above. These scorers require
an `answer` for each sample. Local judging requires a nonempty `rubric` and a local
judge preset. The rubric defines a 0–5 scale; use separate suites for separate
criteria if you need separate metrics. Sample IDs must be unique. Turns are fixed
user messages; each generated assistant reply is included in subsequent context.
This is scripted conversation evaluation, not an autonomous agent environment.

## Resource controls

Participants run sequentially on a dedicated, localhost-only evaluation server.
After their answers are saved and they are unloaded, the local judge runs. Existing
servers are listed for explicit stop confirmation; the panel does not restart them
automatically afterwards. While eval owns the runtime, normal starts, stops,
runtime/settings changes and application updates are rejected to avoid races.

- **Concurrent requests** bounds requests to the model and sets `--parallel`.
- **Context size**, **Batch size** and **Micro-batch size** map to `--ctx-size`,
  `--batch-size` and `--ubatch-size`. Blank values retain preset settings. Context
  allocation across slots depends on the selected runtime; context is not silently
  multiplied or divided by the panel.
- **Max tokens** and **Temperature** apply to evaluation requests; other sampling
  defaults come from the preset/runtime. Snapshots retain explicit flags and the
  inspected runtime version. The runtime's model chat template is used.
- Optional **Throughput calibration** tries concurrency values up to the selected
  ceiling on at most eight samples, selects the measured best token throughput,
  and records the measurements. It does not measure free VRAM or guarantee a fit.
  Load must already fit with the requested maximum number of server slots.
- A recognized OOM, connection failure or model-load failure pauses the run. Reduce
  concurrency/batch sizes and resume, or cancel and change the preset. Context and
  maximum output length are never shortened automatically. An uncommitted batch
  may be retried, but committed samples are not appended twice.
- Pause finishes the current batch before stopping new requests. Cancel interrupts
  requests and unloads the evaluation process. Completed results remain available.

A load timeout and a per-request timeout prevent an indefinitely stuck comparison.
Unknown HTTP failures are recorded as sample errors. A model-supplied judge is not
an objective ground truth; inspect its rationale and keep the same judge settings
when comparing models.

## Storage and lifecycle

`<data_dir>/evaluations/<run_id>/` contains an atomic versioned `run.json` summary,
an immutable `inputs.json` snapshot, and append-only `samples.jsonl`. Samples are
written incrementally; full datasets are not rewritten on every update. Judge
queues hold file offsets rather than all conversations in RAM. Logs remain under
`<data_dir>/instances/<evaluation_instance_id>/llama-server.log`.

Snapshots capture presets, resolved flags, runtime version, generation settings,
dataset hashes/recipes and selected IDs. Model, adapter and runtime files use paths,
sizes and modification times for change detection rather than expensive full GGUF
hashes; these are not cryptographic proof of identical weights.

Graceful panel shutdown cancels its eval task and stops the evaluation server.
After an unexpected panel exit, unfinished history is marked **interrupted**;
there is no automatic resume after restart. A recovered server remains visible in
Servers and must be stopped or explicitly approved for stopping before a new run.
Other servers retain the panel's existing independent-process lifecycle.

The module uses bounded asynchronous HTTP requests and the existing process manager;
it adds no heavyweight ML dependencies to the panel environment.
