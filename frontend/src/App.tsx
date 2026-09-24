import { useEffect, useRef, useState, useMemo } from "react";
import { api as globalApi, instanceApi, instancesApi } from "./api";
import { SettingsPage } from "./components/SettingsPage";
import { InstancesHome } from "./components/InstancesHome";
import type { InstanceView } from "./types";
import { FlagsForm } from "./components/FlagsForm";
import { LogViewer } from "./components/LogViewer";
import { ModelList } from "./components/ModelList";
import { ModelDownload } from "./components/ModelDownload";
import { PresetBar } from "./components/PresetBar";
import { ServerControls } from "./components/ServerControls";
import type {
  BinaryInfo,
  FlagDef,
  FlagValues,
  LoraInfo,
  ModelInfo,
  Preset,
  StatusResponse,
} from "./types";

/** "llama.cpp 0.4.1-dev (build 11026, b49650adb)" for current builds,
 *  "llama.cpp build 6789 (a1b2c3d)" for ones that predate release versions. */
function describeBuild(binary: BinaryInfo): string {
  const details = [
    binary.version !== null && binary.build !== null
      ? `build ${binary.build}`
      : null,
    binary.commit,
  ].filter(Boolean);
  const head = binary.version ?? `build ${binary.build ?? "?"}`;
  return `llama.cpp ${head}${details.length ? ` (${details.join(", ")})` : ""}`;
}

function ServerWorkspace({
  instance,
  onBack,
  navigation,
  onSettings,
  settingsRevision,
  active,
}: {
  instance: InstanceView;
  onBack: () => void;
  navigation: { id: string; view: "configuration" | "logs" } | null;
  onSettings: () => void;
  settingsRevision: number;
  active: boolean;
}) {
  const api = useMemo(() => instanceApi(instance.id), [instance.id]);
  const [saveMessage, setSaveMessage] = useState("");
  const [page, setPage] = useState<"server" | "models" | "loras" | "presets">(
    "server",
  );
  const [tab, setTab] = useState<"overview" | "configuration" | "logs">(
    "configuration",
  );
  useEffect(() => {
    if (navigation?.id !== instance.id) return;
    setPage("server");
    setTab(navigation.view);
  }, [navigation, instance.id]);
  const [search, setSearch] = useState("");
  const [connectionError, setConnectionError] = useState(false);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loras, setLoras] = useState<LoraInfo[]>([]);
  const [schema, setSchema] = useState<FlagDef[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(
    instance.model_id,
  );
  const [values, setValues] = useState<FlagValues>(instance.flags);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [syncedPid, setSyncedPid] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [actionPending, setActionPending] = useState<
    "start" | "stop" | "reload" | null
  >(null);
  const [version, setVersion] = useState<string | null>(null);
  const [runtimeId, setRuntimeId] = useState(instance.runtime_id ?? "default");
  const [runtimes, setRuntimes] = useState<import("./types").RuntimeConfig[]>([]);
  const [runtimePending, setRuntimePending] = useState(false);
  const [runtimeChanged, setRuntimeChanged] = useState(false);
  const runtimeVersion = useRef(0);
  const [binary, setBinary] = useState<BinaryInfo | null>(null);
  // Flags of the last loaded preset that the installed llama-server
  // doesn't know; shown until the user dismisses or loads another preset.
  const [unsupported, setUnsupported] = useState<{
    preset: string;
    keys: string[];
  } | null>(null);
  // Bumped whenever a user action (start/stop/reload/cancel) lands a fresh
  // status, so a poll that was already in flight can tell it is stale.
  const statusVersion = useRef(0);
  const libraryVersion = useRef(0);

  const applyActionStatus = (s: StatusResponse) => {
    statusVersion.current += 1;
    setStatus(s);
  };

  const loadModels = async () => {
    const version = ++libraryVersion.current;
    setModelsLoading(true);
    const results = await Promise.allSettled([
      api.listModels(),
      api.listLoras(),
    ]);
    if (version !== libraryVersion.current) return;
    if (results[0].status === "fulfilled") setModels(results[0].value);
    if (results[1].status === "fulfilled") setLoras(results[1].value);
    const failures = results.filter((result) => result.status === "rejected");
    if (failures.length)
      setError(failures.map((result) => String(result.reason)).join("; "));
    setModelsLoading(false);
  };

  useEffect(() => {
    let active = true;
    loadModels();
    api
      .getHealth()
      .then((h) => setVersion(h.version))
      .catch(() => {});
    api
      .listPresets()
      .then((p) => { if (active) setPresets(p); })
      .catch((e) => { if (active) setError(String(e)); });
    const seen = ++runtimeVersion.current;
    globalApi.getSettings().then(s => {if (active) setRuntimes(s.runtimes);}).catch(e => {if (active) setError(String(e));});
    instancesApi.runtime(instance.id).then(r => {
      if (active && seen === runtimeVersion.current) {
        setRuntimeId(r.runtime_id); setBinary(r.binary); setSchema(r.flags.filter(f => f.key !== "port"));
      }
    }).catch(e => {if (active) setError(String(e));});
    return () => { active = false; libraryVersion.current += 1; };
  }, [settingsRevision, instance.runtime_id]);

  useEffect(() => {
    let disposed = false;
    const poll = () => {
      const seen = statusVersion.current;
      api
        .getStatus()
        .then((s) => {
          // While nothing is running, /status scans OS processes to adopt a
          // stray llama-server, which can take seconds on Windows. A poll
          // that started before the user hit Start therefore lands *after*
          // the Start response and carries a stale "stopped" snapshot. Drop
          // it, or the UI flashes "stopped" and the sync below misfires.
          if (!disposed && statusVersion.current === seen) {
            setStatus(s);
            setConnectionError(false);
          }
        })
        .catch(() => {
          if (!disposed) setConnectionError(true);
        });
    };
    poll();
    const id = setInterval(poll, 5000);
    return () => {
      disposed = true;
      clearInterval(id);
    };
  }, []);

  // If a llama-server is already running (started manually, or left over
  // from a previous panel session) pull its model + flags into the form
  // instead of showing an empty/stale UI. Only syncs the first time a given
  // pid is seen alive, so it never fights the user editing flags: the pid
  // of a server started from this UI is marked synced by the Start/Reload
  // handlers themselves, since the form already holds exactly those flags.
  useEffect(() => {
    if (!status || schema.length === 0) return;
    const isLive = status.state === "running" || status.state === "starting";
    if (!isLive || status.pid === null || status.pid === syncedPid) return;
    setSyncedPid(status.pid);
    if (instance.model_id) return; // Keep a saved draft distinct from running flags.
    if (status.model_id) setSelectedId(status.model_id);
    setValues(
      Object.fromEntries(
        Object.entries(status.flags ?? {}).filter(([key]) => key !== "port"),
      ),
    );
  }, [status, schema, syncedPid]);

  const handleFlagChange = (key: string, value: unknown) => {
    setValues((prev) => {
      const next = { ...prev };
      if (
        value === null ||
        value === undefined ||
        value === "" ||
        (Array.isArray(value) && !value.length)
      )
        delete next[key];
      else next[key] = value as FlagValues[string];
      return next;
    });
  };

  const changeRuntime = async (id: string) => {
    setRuntimePending(true); setError(null); ++runtimeVersion.current;
    try {
      const result = await instancesApi.selectRuntime(instance.id, id);
      setRuntimeId(result.runtime_id); setBinary(result.binary);
      setSchema(result.flags.filter(f => f.key !== "port"));
      setRuntimeChanged(true);
      setPresets(await api.listPresets());
    } catch (e) { setError(String(e)); }
    finally { setRuntimePending(false); }
  };

  const handleStart = () => {
    if (!selectedId) return;
    setError(null);
    setActionPending("start");
    api
      .startServer(selectedId, values)
      .then((s) => {
        setRuntimeChanged(false);
        setSyncedPid(s.pid);
        applyActionStatus(s);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setActionPending(null));
  };

  const handleStop = () => {
    setError(null);
    setActionPending("stop");
    api
      .stopServer()
      .then(applyActionStatus)
      .catch((e) => setError(String(e)))
      .finally(() => setActionPending(null));
  };

  const handleReload = () => {
    if (!selectedId) return;
    setError(null);
    setActionPending("reload");
    api
      .restartServer(selectedId, values)
      .then((r) => {
        setRuntimeChanged(false);
        setSyncedPid(r.status.pid);
        applyActionStatus(r.status);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setActionPending(null));
  };

  const handleCancelRestart = () => {
    setError(null);
    api
      .cancelRestart()
      .then(applyActionStatus)
      .catch((e) => setError(String(e)));
  };

  const handleSavePreset = (name: string) => {
    if (!selectedId) return;
    if (
      presets.some((preset) => preset.name === name) &&
      !window.confirm(
        `Replace preset “${name}” with the current configuration?`,
      )
    )
      return;
    setError(null);
    api
      .savePreset(name, selectedId, values)
      .then((saved) =>
        setPresets((prev) => [
          ...prev.filter((p) => p.name !== saved.name),
          saved,
        ]),
      )
      .catch((e) => setError(String(e)));
  };

  const handleLoadPreset = (preset: Preset) => {
    setSelectedId(preset.model_id);
    setValues(
      Object.fromEntries(
        Object.entries(preset.flags).filter(([key]) => key !== "port"),
      ),
    );
    setUnsupported(
      preset.unsupported.length > 0
        ? { preset: preset.name, keys: preset.unsupported }
        : null,
    );
  };

  const binaryNotice = (() => {
    if (!binary) return null;
    if (binary.error) {
      return (
        <div className="flags-notice warn">
          <span>
            <strong>llama-server could not be probed</strong> ({binary.error}).
            The form below comes from a bundled snapshot of <code>--help</code>{" "}
            and may not match your build.
          </span>
        </div>
      );
    }
    return (
      <div
        className="muted binary-info"
        title={binary.resolved_path ?? undefined}
      >
        {describeBuild(binary)} · {schema.length} flags
      </div>
    );
  })();

  const handleDeletePreset = (name: string) => {
    if (!window.confirm(`Delete preset “${name}”? This cannot be undone.`))
      return;
    setError(null);
    api
      .deletePreset(name)
      .then(() => setPresets((prev) => prev.filter((p) => p.name !== name)))
      .catch((e) => setError(String(e)));
  };

  const runtimeUnsupported = schema.length ? Object.keys(values).filter(key =>
    values[key] !== null && values[key] !== "" && key !== "port" && !schema.some(f => f.key === key)
  ) : [];
  const selectedModel = models.find((m) => m.id === selectedId);
  const live = status?.state === "running" || status?.state === "starting";
  const activeModel = models.find((m) => m.id === status?.model_id);
  const changed =
    live &&
    (runtimeChanged || selectedId !== status?.model_id ||
      schema.some(
        (f) =>
          JSON.stringify(values[f.key] ?? null) !==
          JSON.stringify(status?.flags?.[f.key] ?? null),
      ));
  const configure = () => {
    setPage("server");
    setTab("configuration");
  };
  const filteredModels = models.filter((m) =>
    `${m.display_name} ${m.architecture ?? ""} ${m.entry_path}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  const filteredLoras = loras.filter((l) =>
    `${l.display_name} ${l.base_model ?? ""} ${l.path}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  const presetBar = (
    <PresetBar
      presets={presets}
      canSave={selectedId !== null}
      onLoad={(p) => {
        handleLoadPreset(p);
        configure();
      }}
      onSave={handleSavePreset}
    />
  );

  return (
    <div className="app studio">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="app-header workspace-header">
        <div className="brand">
          <span className="brand-mark">L/</span>LlamaPanel{" "}
          <span className="muted version">{version && `v${version}`}</span>
        </div>
        <nav aria-label="Main navigation">
          {(
            [
              ["server", "Server"],
              ["models", "Models"],
              ["loras", "LoRA library"],
              ["presets", "Presets"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              aria-current={page === key ? "page" : undefined}
              className={page === key ? "chosen" : ""}
              onClick={() => {
                if (key === "server") {
                  configure();
                  return;
                }
                setPage(key);
                setSearch("");
              }}
            >
              {label}
            </button>
          ))}
        </nav>
        <div className="header-actions">
          <span className="muted workspace-label">Local workspace</span>
          <button className="settings-button" onClick={onSettings}>⚙ Settings</button>
        </div>
      </header>
      <main id="main-content">
        <div className="instance-toolbar">
          <button onClick={onBack}>← All servers</button>
          <span className="muted">{instance.name} · Port {instance.port}</span>
        </div>
        {error && (
          <div className="error-banner" role="alert">
            {error}
            <button onClick={() => setError(null)}>Dismiss</button>
          </div>
        )}
        {connectionError && (
          <div className="flags-notice warn" role="status">
            Cannot reach the panel backend. Displayed status may be out of date.
          </div>
        )}
        {page === "server" && (
          <>
            <div className="page-heading">
              <div>
                <p className="eyebrow">Your workspace / Servers</p>
                <h1>{instance.name}</h1>
                <p className="muted">
                  {live
                    ? (activeModel?.display_name ??
                      status?.model_id ??
                      "External model")
                    : "Choose a model and make it your own."}
                </p>
              </div>
            </div>
            <div className="instance-toolbar">
              <button
                onClick={() => {
                  setSaveMessage("");
                  instancesApi
                    .update(instance.id, {
                      name: instance.name,
                      port: instance.port,
                      model_id: selectedId,
                      flags: values,
                    })
                    .then(() => setSaveMessage("Configuration saved"))
                    .catch((e) => setError(String(e)));
                }}
              >
                Save configuration
              </button>
              <span role="status" className="muted">
                {saveMessage}
              </span>
            </div>
            <section
              className="panel server-summary"
              aria-label="Server controls"
            >
              <ServerControls
                status={status}
                canStart={
                  selectedId !== null && !connectionError && status !== null
                }
                pending={runtimePending ? "reload" : actionPending}
                onStart={handleStart}
                onStop={handleStop}
                onReload={handleReload}
                onCancelRestart={handleCancelRestart}
              />
              {changed && (
                <p className="change-note" role="status">
                  Configuration differs from the running server. Apply & restart
                  to use these changes.
                </p>
              )}
            </section>
            <nav className="view-tabs" aria-label="Server views">
              {(["overview", "configuration", "logs"] as const).map((key) => (
                <button
                  key={key}
                  aria-current={tab === key ? "page" : undefined}
                  className={tab === key ? "chosen" : ""}
                  onClick={() => setTab(key)}
                >
                  {key}
                </button>
              ))}
            </nav>
            {tab === "overview" && (
              <div className="overview-grid">
                <section className="panel model-summary">
                  <p className="eyebrow">
                    {live ? "Running model" : "Launch configuration"}
                  </p>
                  <div className="model-symbol" aria-hidden="true">
                    ◇
                  </div>
                  <h2>
                    {(live
                      ? (activeModel?.display_name ?? status?.model_id)
                      : selectedModel?.display_name) ?? "No model selected"}
                  </h2>
                  <p className="muted">
                    {live
                      ? "The model currently served by this instance."
                      : "Select a local GGUF model to prepare this instance."}
                  </p>
                  <button className="primary" onClick={configure}>
                    {selectedId ? "Edit configuration" : "Choose a model"}
                  </button>
                </section>
                <section className="panel">
                  <p className="eyebrow">Instance details</p>
                  <h2>At a glance</h2>
                  <dl className="details-list">
                    <div>
                      <dt>State</dt>
                      <dd>{status?.state ?? "Connecting…"}</dd>
                    </div>
                    <div>
                      <dt>Process</dt>
                      <dd>{status?.pid ?? "Not running"}</dd>
                    </div>
                    <div>
                      <dt>Started</dt>
                      <dd>
                        {status?.started_at
                          ? new Date(status.started_at * 1000).toLocaleString()
                          : "—"}
                      </dd>
                    </div>
                    <div>
                      <dt>Inference</dt>
                      <dd>
                        {!live
                          ? "—"
                          : status?.busy === true
                            ? "Generating"
                            : status?.busy === false
                              ? "Idle"
                              : "Unknown"}
                      </dd>
                    </div>
                    <div>
                      <dt>Configuration model</dt>
                      <dd>
                        {selectedModel?.display_name ??
                          selectedId ??
                          "Not selected"}
                      </dd>
                    </div>
                  </dl>
                  <button onClick={() => setTab("logs")}>
                    Open live logs →
                  </button>
                </section>
                <section className="panel environment">
                  <div>
                    <p className="eyebrow">Runtime</p>
                    <select className="runtime-select" aria-label="Server runtime" value={runtimeId}
                      disabled={runtimePending || actionPending !== null} onChange={e => changeRuntime(e.target.value)}>
                      <option value="default">Default llama-server</option>
                      {runtimes.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
                    </select>
                    {live && <p className="muted">Used on the next start or restart.</p>}
                    {runtimePending && <p className="muted" role="status">Reading runtime flags…</p>}
                    {binaryNotice ?? (
                      <p className="muted">Runtime information unavailable.</p>
                    )}
                  </div>
                  <code className="file-path">
                    {binary?.resolved_path ??
                      binary?.server_bin ??
                      "Binary path unavailable"}
                  </code>
                </section>
              </div>
            )}
            <div hidden={tab !== "configuration"}>
              <section className="panel">
                <div className="panel-header">
                  <div>
                    <p className="eyebrow">Launch configuration</p>
                    <h2>Model & presets</h2>
                  </div>
                </div>
                <p className="muted">
                  Changes are used on the next start or restart.
                </p>
                <label className="field-label">
                  Model
                  <select
                    value={selectedId ?? ""}
                    onChange={(e) => setSelectedId(e.target.value || null)}
                  >
                    <option value="">Select a model</option>
                    {selectedId && !selectedModel && (
                      <option value={selectedId}>
                        {selectedId} (not in library)
                      </option>
                    )}
                    {models.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.display_name}
                      </option>
                    ))}
                  </select>
                </label>
                {presetBar}
              </section>
              <section className="panel configuration-panel">
                <div className="panel-header">
                  <h2>Parameters & adapters</h2>
                  {!binary?.error && binaryNotice}
                </div>
                {binary?.error && binaryNotice}
                {runtimeUnsupported.length > 0 && <p className="flags-notice warn" role="status">
                  Not supported by this runtime (preserved): {runtimeUnsupported.join(", ")}
                </p>}
                {unsupported && (
                  <div className="flags-notice warn">
                    <span>
                      Preset <strong>{unsupported.preset}</strong> contains
                      unsupported flags:{" "}
                      <code>{unsupported.keys.join(", ")}</code>. These will not
                      be passed to this build.
                    </span>
                    <button onClick={() => setUnsupported(null)}>
                      Dismiss
                    </button>
                  </div>
                )}
                <FlagsForm
                  schema={schema}
                  onClear={() => setValues({})}
                  values={values}
                  onChange={handleFlagChange}
                  loras={loras}
                  modelArch={selectedModel?.architecture ?? null}
                />
              </section>
            </div>
          </>
        )}
        {/* Keep the socket and log buffer alive while navigating. */}
        <section
          className="panel logs-panel"
          hidden={page !== "server" || tab !== "logs"}
        >
          <div className="panel-header">
            <h2>Live logs</h2>
            <span className="muted">
              Last 1,000 lines · scroll up to pause following
            </span>
          </div>
          <LogViewer socketUrl={api.logsSocketUrl()} />
        </section>
        {(page === "models" || page === "loras") && (
          <>
            <div className="page-heading">
              <div>
                <p className="eyebrow">Local library</p>
                <h1>{page === "models" ? "Models" : "LoRA adapters"}</h1>
                <p className="muted">
                  {page === "models"
                    ? "Choose the foundation for your server."
                    : "Browse adapters. Connect multiple LoRA and set their scales in server configuration."}
                </p>
              </div>
              <button disabled={modelsLoading} onClick={loadModels}>
                {modelsLoading ? "Scanning…" : "Rescan library"}
              </button>
            </div>
            {page === "models" && <ModelDownload active={active} onComplete={loadModels} />}
            <label className="search-label">
              Search {page === "models" ? "models" : "adapters"}
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Name, architecture or path"
              />
            </label>
            {page === "models" ? (
              <ModelList
                models={filteredModels}
                loading={modelsLoading}
                selectedId={selectedId}
                onSelect={(id) => {
                  setSelectedId(id);
                  configure();
                }}
              />
            ) : modelsLoading ? (
              <p className="muted">Scanning library…</p>
            ) : (
              <div className="library-grid">
                {filteredLoras.map((l) => (
                  <article className="panel" key={l.id}>
                    <p className="eyebrow">
                      LoRA · {(l.size_bytes / 1024 ** 2).toFixed(1)} MiB
                    </p>
                    <h2>{l.display_name}</h2>
                    <p className="muted">
                      {l.base_model ?? "Base model unknown"} ·{" "}
                      {l.architecture ?? "Architecture unknown"}
                    </p>
                    <code className="file-path">{l.path}</code>
                    <p className="muted">Compatibility not verified</p>
                    <button onClick={configure}>Configure adapters →</button>
                  </article>
                ))}
                {!filteredLoras.length && (
                  <p className="muted">
                    {search
                      ? "No adapters match your search."
                      : "No LoRA adapters found. Choose a LoRA directory in Settings."}
                  </p>
                )}
              </div>
            )}
          </>
        )}
        {page === "presets" && (
          <>
            <div className="page-heading">
              <div>
                <p className="eyebrow">Reusable configurations</p>
                <h1>Presets</h1>
                <p className="muted">
                  Save a model and its launch parameters for next time.
                </p>
              </div>
            </div>
            <div className="library-grid">
              {presets.map((p) => (
                <article className="panel" key={p.name}>
                  <p className="eyebrow">Launch preset</p>
                  <h2>{p.name}</h2>
                  <p className="muted">
                    {models.find((m) => m.id === p.model_id)?.display_name ??
                      p.model_id}
                  </p>
                  <button
                    onClick={() => {
                      handleLoadPreset(p);
                      configure();
                    }}
                  >
                    Load configuration →
                  </button>
                  <button
                    type="button"
                    className="danger-button"
                    aria-label={`Delete preset ${p.name}`}
                    onClick={() => handleDeletePreset(p.name)}
                  >
                    Delete preset…
                  </button>
                </article>
              ))}
            </div>
            {!presets.length && (
              <p className="muted">
                No presets yet. Choose a model and save your configuration.
              </p>
            )}
          </>
        )}
      </main>
    </div>
  );
}

export default function App() {
  const [showSettings, setShowSettings] = useState(false);
  const [settingsRevision, setSettingsRevision] = useState(0);
  const [needsSetup, setNeedsSetup] = useState(false);
  useEffect(() => {
    globalApi.getSettings().then(s => setNeedsSetup(s.needs_setup)).catch(() => {});
  }, []);
  const [instances, setInstances] = useState<InstanceView[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [navigation, setNavigation] = useState<{
    id: string;
    view: "configuration" | "logs";
  } | null>(null);
  const [visited, setVisited] = useState<string[]>([]);
  const [error, setError] = useState("");
  const refreshVersion = useRef(0);
  const refresh = () => {
    const version = ++refreshVersion.current;
    return instancesApi
      .list()
      .then((rows) => {
        if (version !== refreshVersion.current) return;
        setInstances(rows);
        setSelected((id) =>
          id && !rows.some((row) => row.id === id) ? null : id,
        );
        setError("");
      })
      .catch((e) => {
        if (version === refreshVersion.current) setError(String(e));
      });
  };
  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, []);
  const open = (id: string, view: "configuration" | "logs" = "configuration") => {
    setVisited((ids) => (ids.includes(id) ? ids : [...ids, id]));
    setSelected(id);
    setNavigation({ id, view });
  };
  return (
    <>
      {showSettings && <SettingsPage onBack={() => setShowSettings(false)} onSaved={s => {
        setNeedsSetup(s.needs_setup);
        setSettingsRevision(v => v + 1);
      }} />}
      <div hidden={showSettings}>
      {error && (
        <div role="alert" className="error-banner">
          {error}
        </div>
      )}
      {selected === null && (
        <InstancesHome
          instances={instances}
          onOpen={open}
          onRefresh={refresh}
          onSettings={() => setShowSettings(true)}
          needsSetup={needsSetup}
        />
      )}
      {instances
        .filter((item) => visited.includes(item.id))
        .map((item) => (
          <div key={item.id} hidden={selected !== item.id}>
            <ServerWorkspace
              active={!showSettings && selected === item.id}
              instance={item}
              navigation={navigation}
              onSettings={() => setShowSettings(true)}
              settingsRevision={settingsRevision}
              onBack={() => {
                setSelected(null);
                refresh();
              }}
            />
          </div>
        ))}
      </div>
    </>
  );
}
