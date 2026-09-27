import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Preset, RuntimeConfig } from "../types";
import { activeStates, evalApi, EvalError } from "../evalApi";
import type {
  ComparisonRequest,
  Library,
  Participant,
  Run,
  Sample,
} from "../evalApi";

const participant = (): Participant => ({
  preset: "",
  runtime_id: "default",
  concurrency: 1,
  max_tokens: 2048,
  temperature: 0,
  ctx_size: null,
  batch_size: null,
  ubatch_size: null,
  calibrate: false,
});
const bytes = (n: number) => `${(n / 1024 / 1024).toFixed(1)} MiB`;

function ParticipantFields({
  value,
  onChange,
  presets,
  runtimes,
  judge = false,
}: {
  value: Participant;
  onChange: (p: Participant) => void;
  presets: Preset[];
  runtimes: RuntimeConfig[];
  judge?: boolean;
}) {
  const change = (key: keyof Participant, next: unknown) =>
    onChange({ ...value, [key]: next });
  const numeric = (
    key: keyof Participant,
    label: string,
    min: number,
    max: number,
    optional = false,
    step = 1,
  ) => (
    <label className="eval-field">
      {label}
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        required={!optional}
        placeholder={optional ? "From preset" : undefined}
        value={value[key] == null ? "" : String(value[key])}
        onChange={(e) =>
          change(key, e.target.value === "" ? null : Number(e.target.value))
        }
      />
    </label>
  );
  return (
    <>
      <div className="eval-fields">
        <label className="eval-field">
          Preset
          <select
            required
            value={value.preset}
            onChange={(e) => change("preset", e.target.value)}
          >
            <option value="">Choose a preset…</option>
            {presets.map((p) => (
              <option key={p.name}>{p.name}</option>
            ))}
          </select>
        </label>
        <label className="eval-field">
          Runtime
          <select
            value={value.runtime_id}
            onChange={(e) => change("runtime_id", e.target.value)}
          >
            <option value="default">Default llama-server</option>
            {runtimes.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
        {!judge && numeric("concurrency", "Concurrent requests", 1, 32)}
        {numeric("max_tokens", "Max tokens", 1, 131072)}
        {numeric("temperature", "Temperature", 0, 2, false, 0.1)}
      </div>
      <details className="eval-details">
        <summary>llama-server settings</summary>
        <div className="eval-fields">
          {numeric("ctx_size", "Context size (tokens)", 512, 2097152, true)}
          {numeric("batch_size", "Batch size (tokens)", 1, 65536, true)}
          {numeric("ubatch_size", "Micro-batch size (tokens)", 1, 65536, true)}
        </div>
        <p className="muted eval-help">
          Server slots match concurrent requests. Context size is passed as
          --ctx-size; its allocation depends on the selected runtime.
        </p>
      </details>
      {!judge && (
        <details className="eval-details">
          <summary>Throughput calibration</summary>
          <label className="eval-check">
            <input
              type="checkbox"
              checked={!!value.calibrate}
              onChange={(e) => change("calibrate", e.target.checked)}
            />{" "}
            Test concurrency up to the selected limit
          </label>
          <p className="muted eval-help">
            Uses up to 8 samples before scoring. Records throughput and pauses
            on resource errors.
          </p>
        </details>
      )}
    </>
  );
}

export function EvaluationsPage({
  active,
  onBack,
  onSettings,
}: {
  active: boolean;
  onBack: () => void;
  onSettings: () => void;
}) {
  const [tab, setTab] = useState<"new" | "library" | "results">("new");
  const [presets, setPresets] = useState<Preset[]>([]);
  const [runtimes, setRuntimes] = useState<RuntimeConfig[]>([]);
  const [participants, setParticipants] = useState<Participant[]>([
    participant(),
    participant(),
  ]);
  const [library, setLibrary] = useState<Library | null>(null);
  const [directory, setDirectory] = useState("");
  const [benchmarks, setBenchmarks] = useState<string[]>([]);
  const [selection, setSelection] = useState<"full" | "custom">("full");
  const [limit, setLimit] = useState("50");
  const [seed, setSeed] = useState("42");
  const [name, setName] = useState("Model comparison");
  const [judge, setJudge] = useState<Participant>(participant());
  const [timeout, setTimeoutValue] = useState("600");
  const [run, setRun] = useState<Run | null>(null);
  const [history, setHistory] = useState<Run[]>([]);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [samplePage, setSamplePage] = useState(0);
  const [showSamples, setShowSamples] = useState(false);
  const [showLogs, setShowLogs] = useState(false);
  const [sampleStatus, setSampleStatus] = useState("all");
  const [sampleParticipants, setSampleParticipants] = useState<number[]>([]);
  const [samplesLoading, setSamplesLoading] = useState(false);
  const logElement = useRef<HTMLPreElement>(null);
  const followLogs = useRef(true);
  const [logs, setLogs] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);
  const [confirm, setConfirm] = useState<{
    request: ComparisonRequest;
    instances: { id: string; name: string }[];
  } | null>(null);
  const [recovery, setRecovery] = useState({
    concurrency: "",
    batch_size: "",
    ubatch_size: "",
  });
  const runId = useRef<string | null>(null);
  const importInput = useRef<HTMLInputElement>(null);
  const running = !!run && activeStates.has(run.state);
  const needsJudge = library?.installed.some(
    (b) => benchmarks.includes(b.id) && b.scorer === "local_judge",
  );
  const setSelectedRun = (r: Run) => {
    runId.current = r.id;
    setRun(r);
    setSamples([]);
    setShowSamples(false);
    setLogs(null);
    setShowLogs(false);
    setSampleStatus("all");
    setSampleParticipants([]);
    followLogs.current = true;
    setSamplePage(0);
  };
  const refreshLibrary = async () => {
    const l = await evalApi<Library>("/library");
    setLibrary(l);
    setDirectory(l.directory);
    setBenchmarks((old) =>
      old.filter((id) => l.installed.some((b) => b.id === id)),
    );
  };
  const refreshHistory = async () => setHistory(await evalApi<Run[]>("/runs"));
  const act = async (f: () => Promise<void>) => {
    setPending(true);
    setError("");
    setMessage("");
    try {
      await f();
    } catch (e) {
      setError(String(e));
    } finally {
      setPending(false);
    }
  };
  useEffect(() => {
    if (!active) return;
    let disposed = false;
    Promise.all([
      api.listPresets(),
      api.getSettings(),
      evalApi<Library>("/library"),
      evalApi<Run[]>("/runs"),
      evalApi<Run | null>("/active"),
    ])
      .then(([p, s, l, h, r]) => {
        if (disposed) return;
        setPresets(p);
        setRuntimes(s.runtimes);
        setLibrary(l);
        setDirectory(l.directory);
        setHistory(h);
        if (r) {
          setSelectedRun(r);
          setTab("results");
        }
      })
      .catch((e) => {
        if (!disposed) setError(String(e));
      });
    return () => {
      disposed = true;
    };
  }, [active]);
  useEffect(() => {
    if (!active || (!running && library?.download.state !== "downloading"))
      return;
    let disposed = false;
    let timer: ReturnType<typeof window.setTimeout>;
    const controller = new AbortController();
    const poll = async () => {
      if (!document.hidden) {
        try {
          const id = runId.current;
          if (running && id) {
            const next = await evalApi<Run>(
              `/runs/${id}`,
              "GET",
              undefined,
              controller.signal,
            );
            if (!disposed && runId.current === id) {
              setRun(next);
              if (!activeStates.has(next.state)) await refreshHistory();
            }
          }
          if (library?.download.state === "downloading") {
            const next = await evalApi<Library>(
              "/library",
              "GET",
              undefined,
              controller.signal,
            );
            if (!disposed) setLibrary(next);
          }
        } catch (e) {
          if (!disposed) setError(String(e));
        }
      }
      if (!disposed) timer = window.setTimeout(poll, 2000);
    };
    timer = window.setTimeout(poll, 2000);
    return () => {
      disposed = true;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [active, running, library?.download.state]);
  const submit = async (request: ComparisonRequest) => {
    try {
      const next = await evalApi<Run>("/runs", "POST", request);
      setSelectedRun(next);
      setTab("results");
      setConfirm(null);
      await refreshHistory();
    } catch (e) {
      if (
        e instanceof EvalError &&
        e.detail &&
        typeof e.detail === "object" &&
        "instances" in e.detail
      ) {
        setConfirm({
          request,
          instances: (e.detail as { instances: { id: string; name: string }[] })
            .instances,
        });
      } else throw e;
    }
  };
  useEffect(() => {
    if (!active || tab !== "results" || !run || (!showSamples && !showLogs))
      return;
    const id = run.id;
    let disposed = false;
    let timer: ReturnType<typeof window.setTimeout>;
    const controller = new AbortController();
    const poll = async () => {
      try {
        const query = new URLSearchParams({
          offset: String(samplePage * 50),
          limit: "51",
          status: sampleStatus,
        });
        sampleParticipants.forEach((i) =>
          query.append("participant", String(i)),
        );
        await Promise.all([
          showSamples
            ? evalApi<Sample[]>(
                `/runs/${id}/samples?${query}`,
                "GET",
                undefined,
                controller.signal,
              ).then((rows) => {
                if (!disposed && runId.current === id) {
                  setSamples(rows);
                  setSamplesLoading(false);
                }
              })
            : Promise.resolve(),
          showLogs
            ? evalApi<{ text: string }>(
                `/runs/${id}/logs`,
                "GET",
                undefined,
                controller.signal,
              ).then((value) => {
                if (!disposed && runId.current === id) setLogs(value.text);
              })
            : Promise.resolve(),
        ]);
      } catch (e) {
        if (!disposed) {
          setError(String(e));
          setSamplesLoading(false);
        }
      }
      if (!disposed && running) timer = window.setTimeout(poll, 2000);
    };
    if (showSamples) setSamplesLoading(true);
    void poll();
    return () => {
      disposed = true;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [
    active,
    tab,
    run?.id,
    run?.state,
    showLogs,
    showSamples,
    samplePage,
    sampleStatus,
    sampleParticipants,
  ]);
  useEffect(() => {
    if (followLogs.current && logElement.current)
      logElement.current.scrollTop = logElement.current.scrollHeight;
  }, [logs]);
  return (
    <div className="app studio eval-page">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark">L/</span>LlamaPanel
        </div>
        <nav aria-label="Main navigation">
          <button onClick={onBack}>Servers</button>
        </nav>
        <button className="settings-button" onClick={onSettings}>
          ⚙ Settings
        </button>
      </header>
      <main>
        <div className="page-heading">
          <h1>Evaluations</h1>
        </div>
        <nav className="eval-tabs" aria-label="Evaluation views">
          {(["new", "library", "results"] as const).map((t) => (
            <button
              key={t}
              aria-current={tab === t ? "page" : undefined}
              onClick={() => {
                setTab(t);
                if (t === "results") void act(refreshHistory);
              }}
            >
              {t === "new"
                ? "New comparison"
                : t === "library"
                  ? "Benchmark library"
                  : "Results"}
            </button>
          ))}
        </nav>
        {error && (
          <div role="alert" className="error-banner">
            {error}
          </div>
        )}
        {message && <p role="status">{message}</p>}
        {confirm && (
          <section className="panel eval-confirm" role="alert">
            <h2>Stop running servers?</h2>
            <p>{confirm.instances.map((i) => i.name).join(", ")}</p>
            <p className="muted">
              These servers will remain stopped after the comparison.
            </p>
            <div className="eval-actions">
              <button
                className="primary"
                disabled={pending}
                onClick={() =>
                  void act(() =>
                    submit({
                      ...confirm.request,
                      stop_instances: [
                        ...(confirm.request.stop_instances ?? []),
                        ...confirm.instances.map((i) => i.id),
                      ],
                    }),
                  )
                }
              >
                Stop and run
              </button>
              <button onClick={() => setConfirm(null)}>Cancel</button>
            </div>
          </section>
        )}
        {tab === "new" && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void act(() =>
                submit({
                  name,
                  participants,
                  benchmarks,
                  sample_selection: selection,
                  sample_limit: selection === "custom" ? Number(limit) : null,
                  seed: Number(seed),
                  judge: needsJudge ? judge : null,
                  stop_instances: [],
                  request_timeout: Number(timeout),
                  load_timeout: Number(timeout),
                }),
              );
            }}
          >
            <fieldset disabled={pending || running} className="eval-form">
              <section className="panel eval-section">
                <div className="panel-header">
                  <h2>Participants</h2>
                  <button
                    type="button"
                    disabled={participants.length >= 8}
                    onClick={() =>
                      setParticipants((p) => [...p, participant()])
                    }
                  >
                    + Add participant
                  </button>
                </div>
                <div className="eval-participants">
                  {participants.map((p, i) => (
                    <div className="eval-participant" key={i}>
                      <div className="panel-header">
                        <h3>{i === 0 ? "Baseline" : `Participant ${i + 1}`}</h3>
                        <button
                          type="button"
                          disabled={participants.length === 1}
                          onClick={() =>
                            setParticipants((ps) =>
                              ps.filter((_, j) => i !== j),
                            )
                          }
                        >
                          Remove
                        </button>
                      </div>
                      <ParticipantFields
                        value={p}
                        presets={presets}
                        runtimes={runtimes}
                        onChange={(v) =>
                          setParticipants((ps) =>
                            ps.map((old, j) => (j === i ? v : old)),
                          )
                        }
                      />
                    </div>
                  ))}
                </div>
                <p className="muted eval-help">
                  Changes apply to this comparison only; saved presets stay
                  unchanged.
                </p>
              </section>
              <section className="panel eval-section">
                <div className="panel-header">
                  <h2>Benchmarks</h2>
                  <button type="button" onClick={() => setTab("library")}>
                    Manage library
                  </button>
                </div>
                {!library?.installed.length && (
                  <p className="muted eval-help">
                    Download a benchmark or import a suite in Benchmark library.
                  </p>
                )}
                {library?.installed.map((b) => (
                  <label className="eval-benchmark" key={b.id}>
                    <input
                      type="checkbox"
                      disabled={!!b.error}
                      checked={benchmarks.includes(b.id)}
                      onChange={(e) =>
                        setBenchmarks((ids) =>
                          e.target.checked
                            ? [...ids, b.id]
                            : ids.filter((id) => id !== b.id),
                        )
                      }
                    />
                    <span>
                      <strong>{b.name}</strong>
                      <span className="muted">
                        {b.error ||
                          `${b.samples.toLocaleString()} samples · ${b.scorer?.replace(/_/g, " ")}`}
                      </span>
                    </span>
                  </label>
                ))}
                <div className="eval-fields eval-selection">
                  <label className="eval-field">
                    Sample selection
                    <select
                      value={selection}
                      onChange={(e) =>
                        setSelection(e.target.value as "full" | "custom")
                      }
                    >
                      <option value="full">Full</option>
                      <option value="custom">Custom</option>
                    </select>
                  </label>
                  {selection === "custom" && (
                    <label className="eval-field">
                      Samples per benchmark
                      <input
                        required
                        type="number"
                        min="1"
                        max="20000"
                        value={limit}
                        onChange={(e) => setLimit(e.target.value)}
                      />
                    </label>
                  )}
                  <label className="eval-field">
                    Random seed
                    <input
                      required
                      type="number"
                      min="0"
                      max="2147483647"
                      value={seed}
                      onChange={(e) => setSeed(e.target.value)}
                    />
                  </label>
                </div>
              </section>
              {needsJudge && (
                <section className="panel eval-section">
                  <h2>Local judge</h2>
                  <ParticipantFields
                    judge
                    value={judge}
                    onChange={setJudge}
                    presets={presets}
                    runtimes={runtimes}
                  />
                  <p className="muted eval-help">
                    Scores saved conversations after all participants are
                    unloaded.
                  </p>
                </section>
              )}
              <details className="panel eval-section">
                <summary>Run settings</summary>
                <div className="eval-fields">
                  <label className="eval-field">
                    Comparison name
                    <input
                      required
                      maxLength={120}
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                    />
                  </label>
                  <label className="eval-field">
                    Timeout (seconds)
                    <input
                      required
                      type="number"
                      min="10"
                      max="7200"
                      value={timeout}
                      onChange={(e) => setTimeoutValue(e.target.value)}
                    />
                  </label>
                </div>
              </details>
              <div className="eval-footer">
                <span>
                  {participants.length} participants · {benchmarks.length}{" "}
                  benchmarks
                </span>
                <button
                  className="primary"
                  disabled={!benchmarks.length || !presets.length || !!confirm}
                  type="submit"
                >
                  Run comparison
                </button>
              </div>
            </fieldset>
            {running && (
              <p className="muted">
                A comparison is active. Open Results to pause or cancel it.
              </p>
            )}
          </form>
        )}
        {tab === "library" && (
          <>
            <section className="panel eval-section">
              <h2>Benchmark storage</h2>
              <div className="eval-path">
                <label className="eval-field">
                  Dataset directory
                  <input
                    value={directory}
                    onChange={(e) => setDirectory(e.target.value)}
                  />
                </label>
                <button
                  disabled={pending || running}
                  onClick={() =>
                    void act(async () => {
                      const picked = await api.pickPath("directory", directory);
                      if (picked.path) setDirectory(picked.path);
                      else if (!picked.available)
                        setMessage(
                          "System picker unavailable. Enter an absolute path.",
                        );
                    })
                  }
                >
                  Browse
                </button>
                <button
                  disabled={
                    pending || running || directory === library?.directory
                  }
                  onClick={() =>
                    void act(async () => {
                      await evalApi("/library/storage", "PUT", { directory });
                      await refreshLibrary();
                    })
                  }
                >
                  Save
                </button>
              </div>
              <p className="muted eval-help">
                Changing folders switches libraries. Existing files stay in
                their current folder.
              </p>
            </section>
            <section className="panel eval-section">
              <div className="panel-header">
                <h2>Installed benchmarks</h2>
                <button
                  disabled={pending || running}
                  onClick={() => importInput.current?.click()}
                >
                  Import JSON
                </button>
                <input
                  ref={importInput}
                  hidden
                  type="file"
                  accept=".json,application/json"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    e.target.value = "";
                    if (file)
                      void act(async () => {
                        if (file.size > 32 * 1024 * 1024)
                          throw Error("Suite exceeds 32 MiB");
                        await evalApi(
                          "/library/import",
                          "POST",
                          JSON.parse(await file.text()),
                        );
                        await refreshLibrary();
                      });
                  }}
                />
              </div>
              {!library?.installed.length && (
                <p className="muted eval-help">No benchmarks installed.</p>
              )}
              {library?.installed.map((b) => (
                <div className="eval-library-row" key={b.id}>
                  <div>
                    <h3>{b.name}</h3>
                    <p className="muted">
                      {b.error ||
                        `${b.samples.toLocaleString()} samples · ${bytes(b.bytes ?? 0)} · ${b.scorer?.replace(/_/g, " ")}`}
                    </p>
                    <details>
                      <summary>Details</summary>
                      <p className="muted">{b.description}</p>
                      <p className="muted">{b.recipe}</p>
                      <code>{b.id}</code>
                    </details>
                  </div>
                  <button
                    disabled={pending || running}
                    onClick={() =>
                      void act(async () => {
                        if (
                          window.confirm(
                            `Remove local data for ${b.name}? Saved comparison results are retained.`,
                          )
                        ) {
                          await evalApi(`/library/${b.id}`, "DELETE");
                          await refreshLibrary();
                        }
                      })
                    }
                  >
                    Remove data
                  </button>
                </div>
              ))}
            </section>
            <section className="panel eval-section">
              <h2>Download benchmarks</h2>
              {library?.catalog.map((c) => (
                <div className="eval-library-row" key={c.id}>
                  <div>
                    <h3>{c.name}</h3>
                    <p className="muted">{c.description}</p>
                    <small>
                      {bytes(c.download_bytes)} · {c.license} ·{" "}
                      <a href={c.source} target="_blank" rel="noreferrer">
                        Source
                      </a>
                    </small>
                  </div>
                  <button
                    disabled={
                      pending ||
                      running ||
                      library.download.state === "downloading"
                    }
                    onClick={() =>
                      void act(async () => {
                        await evalApi(`/library/download/${c.id}`, "POST");
                        await refreshLibrary();
                      })
                    }
                  >
                    {library.installed.some((b) => b.catalog_id === c.id)
                      ? "Update"
                      : "Download"}
                  </button>
                </div>
              ))}
              {library?.download.state === "downloading" && (
                <div className="eval-actions">
                  <span role="status">
                    Downloading · {bytes(library.download.bytes)}
                  </span>
                  <button
                    onClick={() =>
                      void act(async () => {
                        await evalApi("/library/download-cancel", "POST");
                        await refreshLibrary();
                      })
                    }
                  >
                    Cancel download
                  </button>
                </div>
              )}
              {library?.download.state === "failed" && (
                <p role="alert" className="error-banner">
                  {library.download.error}
                </p>
              )}
              <p className="muted eval-help">
                Custom JSON suites support exact answers and multi-turn
                conversations with a local judge. Format: docs/evaluations.md.
              </p>
            </section>
          </>
        )}
        {tab === "results" && (
          <>
            <section className="panel eval-section">
              <h2>Comparisons</h2>
              {!history.length && (
                <p className="muted eval-help">No comparisons yet.</p>
              )}
              {history.map((h) => (
                <div className="eval-library-row" key={h.id}>
                  <div>
                    <h3>{h.name}</h3>
                    <small>
                      {new Date(h.created_at * 1000).toLocaleString()} ·{" "}
                      {h.state}
                    </small>
                  </div>
                  <button
                    disabled={pending}
                    onClick={() =>
                      void act(async () =>
                        setSelectedRun(await evalApi<Run>(`/runs/${h.id}`)),
                      )
                    }
                  >
                    Open
                  </button>
                </div>
              ))}
            </section>
            {run && (
              <section className="panel eval-section">
                <div className="panel-header">
                  <div>
                    <h2>{run.name}</h2>
                    <p className="muted">
                      {run.state}{" "}
                      {run.current && running ? `· ${run.current}` : ""}
                    </p>
                  </div>
                  {running && (
                    <div className="eval-actions">
                      {["running", "judging", "calibrating"].includes(
                        run.state,
                      ) && (
                        <button
                          disabled={pending}
                          onClick={() =>
                            void act(async () =>
                              setRun(
                                await evalApi<Run>(
                                  `/runs/${run.id}/pause`,
                                  "POST",
                                ),
                              ),
                            )
                          }
                        >
                          Pause
                        </button>
                      )}
                      <button
                        disabled={pending || run.state === "cancelling"}
                        onClick={() =>
                          void act(async () => {
                            setRun(
                              await evalApi<Run>(
                                `/runs/${run.id}/cancel`,
                                "POST",
                              ),
                            );
                            await refreshHistory();
                          })
                        }
                      >
                        Cancel
                      </button>
                    </div>
                  )}
                </div>
                {running && (
                  <>
                    <progress
                      aria-label="Evaluation progress"
                      max={
                        run.phase === "judging" ? run.judge_total : run.total
                      }
                      value={
                        run.phase === "judging"
                          ? run.judge_completed
                          : run.completed
                      }
                    />
                    <p className="muted">
                      {run.phase === "judging"
                        ? `${run.judge_completed} / ${run.judge_total} judged`
                        : `${run.completed} / ${run.total} samples`}
                    </p>
                  </>
                )}
                {run.error && (
                  <p role="alert" className="error-banner">
                    {run.error}
                  </p>
                )}
                {run.state === "paused" && (
                  <div className="eval-recovery">
                    {run.error && (
                      <div className="eval-fields">
                        {(
                          ["concurrency", "batch_size", "ubatch_size"] as const
                        ).map((key, i) => (
                          <label className="eval-field" key={key}>
                            {
                              [
                                "Concurrent requests",
                                "Batch size (tokens)",
                                "Micro-batch size (tokens)",
                              ][i]
                            }
                            <input
                              type="number"
                              min="1"
                              placeholder="Keep current"
                              value={recovery[key]}
                              onChange={(e) =>
                                setRecovery((r) => ({
                                  ...r,
                                  [key]: e.target.value,
                                }))
                              }
                            />
                          </label>
                        ))}
                      </div>
                    )}
                    <button
                      disabled={pending}
                      onClick={() =>
                        void act(async () => {
                          const body = run.error
                            ? Object.fromEntries(
                                Object.entries(recovery)
                                  .filter(([, v]) => v !== "")
                                  .map(([k, v]) => [k, Number(v)]),
                              )
                            : {};
                          setRun(
                            await evalApi<Run>(
                              `/runs/${run.id}/resume`,
                              "POST",
                              body,
                            ),
                          );
                          setRecovery({
                            concurrency: "",
                            batch_size: "",
                            ubatch_size: "",
                          });
                        })
                      }
                    >
                      Resume
                    </button>
                  </div>
                )}
                <div className="eval-table">
                  <table>
                    <thead>
                      <tr>
                        <th>Benchmark</th>
                        {run.participants?.map((p, i) => (
                          <th key={i}>{p.preset}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {Array.from(
                        new Set(
                          Object.values(run.metrics ?? {}).map(
                            (m) => m.benchmark,
                          ),
                        ),
                      ).map((id) => {
                        const row = Object.values(run.metrics).filter(
                          (m) => m.benchmark === id,
                        );
                        return (
                          <tr key={id}>
                            <th>
                              {row[0].name}
                              <small>{row[0].metric}</small>
                            </th>
                            {run.participants.map((_, i) => {
                              const m = row.find((r) => r.participant === i);
                              return (
                                <td key={i}>
                                  {m?.score == null
                                    ? "—"
                                    : m.metric === "accuracy"
                                      ? `${(m.score * 100).toFixed(1)}%`
                                      : m.score.toFixed(2)}
                                  <small>
                                    {m
                                      ? `${m.scored}/${m.total} scored · ${m.errors} errors`
                                      : "Pending"}
                                  </small>
                                </td>
                              );
                            })}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <section className="eval-result-section">
                  <button
                    aria-expanded={showLogs}
                    aria-controls="eval-run-logs"
                    onClick={() => setShowLogs((v) => !v)}
                  >
                    Logs
                  </button>
                  {showLogs && (
                    <pre
                      id="eval-run-logs"
                      className="eval-output eval-live-logs"
                      ref={logElement}
                      onScroll={(e) => {
                        const el = e.currentTarget;
                        followLogs.current =
                          el.scrollHeight - el.scrollTop - el.clientHeight < 40;
                      }}
                    >
                      {logs === null ? "Loading logs…" : logs || "No logs yet."}
                    </pre>
                  )}
                </section>
                <details className="eval-details">
                  <summary>Configuration & calibration</summary>
                  <pre className="eval-output">
                    {JSON.stringify(run.participants, null, 2)}
                  </pre>
                  <button
                    onClick={() => {
                      const blob = new Blob([JSON.stringify(run, null, 2)], {
                        type: "application/json",
                      });
                      const url = URL.createObjectURL(blob);
                      const a = document.createElement("a");
                      a.href = url;
                      a.download = `comparison-${run.id}.json`;
                      a.click();
                      URL.revokeObjectURL(url);
                    }}
                  >
                    Export summary
                  </button>
                </details>
                <section className="eval-result-section">
                  <button
                    aria-expanded={showSamples}
                    aria-controls="eval-run-answers"
                    onClick={() => setShowSamples((v) => !v)}
                  >
                    Inspect answers
                  </button>
                  {showSamples && (
                    <div className="eval-samples" id="eval-run-answers">
                      <div className="eval-answer-filters">
                        <label>
                          Status
                          <select
                            value={sampleStatus}
                            onChange={(e) => {
                              setSampleStatus(e.target.value);
                              setSamplePage(0);
                              setSamples([]);
                            }}
                          >
                            <option value="all">All</option>
                            <option value="passed">Passed</option>
                            <option value="failed">Failed</option>
                            <option value="error">Errors</option>
                            <option value="pending">Pending score</option>
                            <option value="scored">Judge scored</option>
                          </select>
                        </label>
                        <fieldset>
                          <legend>Participants</legend>
                          <label>
                            <input
                              type="checkbox"
                              checked={sampleParticipants.length === 0}
                              onChange={() => {
                                setSampleParticipants([]);
                                setSamplePage(0);
                                setSamples([]);
                              }}
                            />
                            All
                          </label>
                          {run.participants.map((p, i) => (
                            <label key={i}>
                              <input
                                type="checkbox"
                                checked={sampleParticipants.includes(i)}
                                onChange={() => {
                                  setSampleParticipants((old) =>
                                    old.includes(i)
                                      ? old.filter((n) => n !== i)
                                      : [...old, i],
                                  );
                                  setSamplePage(0);
                                  setSamples([]);
                                }}
                              />
                              {p.preset}
                            </label>
                          ))}
                        </fieldset>
                      </div>
                      {samples.length === 0 && (
                        <p className="muted">
                          {samplesLoading
                            ? "Loading answers…"
                            : "No matching answers yet."}
                        </p>
                      )}
                      {samples.slice(0, 50).map((s) => (
                        <details
                          className="eval-details"
                          key={`${s.participant}:${s.benchmark}:${s.sample_id}`}
                        >
                          <summary>
                            {run.participants[s.participant]?.preset} · Sample{" "}
                            {s.sample_id} · {s.status}
                            {s.score != null && ` · Score: ${s.score}`}
                          </summary>
                          {s.error && <p className="error-banner">{s.error}</p>}
                          {s.messages?.map((m, j) => (
                            <div key={j}>
                              <strong>{m.role}</strong>
                              <pre className="eval-output">{m.content}</pre>
                            </div>
                          ))}
                          {s.expected != null && <p>Expected: {s.expected}</p>}
                          {s.judge_output && (
                            <pre className="eval-output">{s.judge_output}</pre>
                          )}
                        </details>
                      ))}
                      <div className="eval-actions">
                        <button
                          disabled={samplesLoading || samplePage === 0}
                          onClick={() => (
                            setSamples([]),
                            setSamplePage(samplePage - 1)
                          )}
                        >
                          Previous
                        </button>
                        <span>Page {samplePage + 1}</span>
                        <button
                          disabled={samplesLoading || samples.length <= 50}
                          onClick={() => (
                            setSamples([]),
                            setSamplePage(samplePage + 1)
                          )}
                        >
                          Next
                        </button>
                      </div>
                    </div>
                  )}
                </section>
              </section>
            )}
          </>
        )}
      </main>
    </div>
  );
}
