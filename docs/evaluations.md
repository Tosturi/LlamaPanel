# Model evaluations

[Documentation](README.md)

Open **Evaluations** from Servers or a server workspace. Add participants using
saved presets, select each participant's runtime, choose an engine and benchmarks,
and run a comparison. A preset can reference a base GGUF, a different quantization,
or LoRA adapters. For before/after training, create separate presets first.

## Samples and results

**Full** runs the complete installed suite. **Custom** requires a positive number
of samples per benchmark. If a suite is smaller than that limit, all its samples
are used. A seeded selection is made once and reused for every participant.

Results include individual answers, conversations, errors, local-judge output,
and configuration snapshots. Accuracy is reported over successfully scored
samples; errors and the scored/total count are shown separately. Do not compare
scores without checking those counts. For native suites, output truncated at
the token limit is an error. Harness applies the selected task's scoring to
outputs within the requested token budget. There is no aggregate quality score across unrelated tests.

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

The native engine supports text generation, exact/numeric scoring and fixed
multi-turn scripts with a local judge. Select the optional lm-evaluation-harness
engine for its supported generation and loglikelihood tasks (see below).
Tool/environment agent benchmarks and Inspect tasks are not supported.

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

### Inspecting an active comparison

Logs and Inspect answers are independent collapsible sections. While expanded,
they refresh every two seconds during a run and once more at completion. Logs
follow new output unless you scroll up. Completed runs retain their own log file.
The viewer shows the last 32 KB; the full archive is stored with the run.

Answer filters apply before pagination. Select one or more participants, or All.
Passed/Failed apply to accuracy scorers; Errors and Pending score are separate.
Local judge results use Judge scored and display the numeric score, without an
implicit pass threshold. A judge result replaces its pending generation entry in
the viewer; both original records remain in the JSONL archive.

Catalog entries show Update while a downloaded revision remains installed and
Download after it is removed. Update checks the catalog's pinned source; identical
content is deduplicated. It does not silently change snapshots of earlier runs.

## lm-evaluation-harness

Select **lm-evaluation-harness** as the engine and install it once from the
comparison form. The panel creates an independent Python environment under
`<data_dir>/harness/venv`; installation needs internet access and Python's `venv`
and `pip`. Its dependencies do not replace the panel's dependencies. The engine
is pinned to upstream revision `d6de81643928d653435c431bae19945d41d32520`.
Installation output is saved in `<data_dir>/harness/install.log`.

The initial task selection includes GSM8K, IFEval, ARC Easy/Challenge, HellaSwag,
Winogrande and BoolQ. Harness owns their prompt construction, few-shot selection,
answer extraction and metrics. Required data is fetched using Hugging Face's
cache under `<data_dir>/harness/hf-cache` before the panel stops existing servers.
The confirmation to stop servers still applies. Dataset and custom-task browsing
are not part of this integration.

- **Few-shot examples**: leave empty for the task default, or specify zero or more.
- **Apply model chat template**: use the selected server's template via
  `/apply-template`. Disabled uses the task's plain completion prompts.
- **Max sequence length**: the prompt plus requested output budget for one slot.
  The panel checks the actual context reported by `/props`. Oversized prompts
  fail instead of being silently truncated.
- **Concurrent requests**: controls harness parallelism and `llama-server --parallel`.
  For this HTTP backend, harness's usual `batch_size` is not a VRAM auto-tuner.
- **Context size**, **Batch size** and **Micro-batch size** are llama-server token
  settings (`--ctx-size`, `--batch-size`, `--ubatch-size`). Model/CPU offload,
  flash attention and KV cache types continue to come from the participant preset.
  With runtimes that divide total context between slots, four 4096-token slots
  require at least 16384 total context tokens. Verify actual allocation on the
  selected runtime; increasing concurrency can increase memory use.

Start with one request, then raise concurrency in later comparisons while keeping
the same task, seeds and generation settings. There is no guaranteed OOM-free
configuration or automatic VRAM estimator. The native suite's throughput
calibration is not applied to harness tasks. A resource failure stops the server
and pauses the run. Resume can lower concurrency and adjust token batch sizes;
it does not shrink sequence length, output budget or benchmark content.
Completed request responses are cached on disk per participant/task and reused
when retrying that task. Cache identities exclude slot numbers so reducing
concurrency does not invalidate successful requests.

The GGUF backend uses `/v1/completions` and the server's `/tokenize`. Likelihood
tasks require modern token IDs and logprobs, verified with a capability probe.
They score continuation tokens separately and can be substantially slower than
ordinary generation. Per-slot serialization preserves KV cache ownership;
different slots can score questions concurrently. Rolling likelihood/perplexity,
multimodal tasks and tasks that execute generated code are not exposed.

Runs store task configurations, dataset split fingerprints and selected document
indices. Fingerprints must match across participants. Full harness results,
including all metrics, filters, per-sample responses and effective configuration,
are retained under `evaluations/<run_id>/harness/<participant>/<task>/results.json`
and can be exported from **Configuration & calibration**. Dataset fingerprints
identify cached inputs; they do not guarantee that an upstream dataset will
remain downloadable forever.

During inference the UI reports model requests, which may outnumber documents
for multiple-choice tasks. Scores and answer inspection become available when a
task finishes scoring. Logs include both llama-server and harness output. Pause
drains the current request batch; cancel terminates the worker and stops its
server. Panel restart marks unfinished runs interrupted, without automatic resume.

## Exporting and deleting comparisons

In **Results → Comparisons**, completed, failed, cancelled and interrupted runs
have **Export HTML** and **Delete** actions. HTML reports are standalone files
that open offline and contain the metric table, configuration/provenance and all
recorded answers, including judge output and harness sample metrics. Answer
sections can be expanded individually. The report uses the latest record for
each sample and is not restricted by the viewer's current page or filters.

Delete asks for confirmation and removes that run's results, inputs, logs,
response caches and configuration. Installed datasets, presets and other runs
remain available. Active or paused runs must finish or be cancelled first.
