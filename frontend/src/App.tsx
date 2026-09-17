import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { FlagsForm } from "./components/FlagsForm";
import { LogViewer } from "./components/LogViewer";
import { ModelList } from "./components/ModelList";
import { PresetBar } from "./components/PresetBar";
import { ServerControls } from "./components/ServerControls";
import type { BinaryInfo, FlagDef, FlagValues, LoraInfo, ModelInfo, Preset, StatusResponse } from "./types";

function defaultsFromSchema(schema: FlagDef[]): FlagValues {
  const values: FlagValues = {};
  for (const f of schema) values[f.key] = f.default ?? null;
  return values;
}

/** "llama.cpp 0.4.1-dev (build 11026, b49650adb)" for current builds,
 *  "llama.cpp build 6789 (a1b2c3d)" for ones that predate release versions. */
function describeBuild(binary: BinaryInfo): string {
  const details = [
    binary.version !== null && binary.build !== null ? `build ${binary.build}` : null,
    binary.commit,
  ].filter(Boolean);
  const head = binary.version ?? `build ${binary.build ?? "?"}`;
  return `llama.cpp ${head}${details.length ? ` (${details.join(", ")})` : ""}`;
}

export default function App() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loras, setLoras] = useState<LoraInfo[]>([]);
  const [schema, setSchema] = useState<FlagDef[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [values, setValues] = useState<FlagValues>({});
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [syncedPid, setSyncedPid] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [actionPending, setActionPending] = useState<"start" | "stop" | "reload" | null>(null);
  const [version, setVersion] = useState<string | null>(null);
  const [binary, setBinary] = useState<BinaryInfo | null>(null);
  // Flags of the last loaded preset that the installed llama-server
  // doesn't know; shown until the user dismisses or loads another preset.
  const [unsupported, setUnsupported] = useState<{ preset: string; keys: string[] } | null>(null);
  // Bumped whenever a user action (start/stop/reload/cancel) lands a fresh
  // status, so a poll that was already in flight can tell it is stale.
  const statusVersion = useRef(0);

  const applyActionStatus = (s: StatusResponse) => {
    statusVersion.current += 1;
    setStatus(s);
  };

  const loadModels = () => {
    setModelsLoading(true);
    // Same directory, same rescan button: adapters are refreshed with the models.
    api.listLoras().then(setLoras).catch(() => {});
    return api.listModels().then(setModels).catch((e) => setError(String(e))).finally(() => setModelsLoading(false));
  };

  useEffect(() => {
    loadModels();
    api.getHealth().then((h) => setVersion(h.version)).catch(() => {});
    api.listPresets().then(setPresets).catch((e) => setError(String(e)));
    api.getFlagSchema().then((s) => {
      setSchema(s);
      setValues(defaultsFromSchema(s));
    }).catch((e) => setError(String(e)));
    api.getBinaryInfo().then(setBinary).catch(() => {});
  }, []);

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
          if (!disposed && statusVersion.current === seen) setStatus(s);
        })
        .catch(() => {});
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
    if (status.model_id) setSelectedId(status.model_id);
    setValues({ ...defaultsFromSchema(schema), ...(status.flags ?? {}) });
  }, [status, schema, syncedPid]);

  const handleFlagChange = (key: string, value: unknown) => {
    setValues((prev) => ({ ...prev, [key]: value as FlagValues[string] }));
  };

  const handleStart = () => {
    if (!selectedId) return;
    setError(null);
    setActionPending("start");
    api
      .startServer(selectedId, values)
      .then((s) => {
        setSyncedPid(s.pid);
        applyActionStatus(s);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setActionPending(null));
  };

  const handleStop = () => {
    setError(null);
    setActionPending("stop");
    api.stopServer().then(applyActionStatus).catch((e) => setError(String(e))).finally(() => setActionPending(null));
  };

  const handleReload = () => {
    if (!selectedId) return;
    setError(null);
    setActionPending("reload");
    api
      .restartServer(selectedId, values)
      .then((r) => {
        setSyncedPid(r.status.pid);
        applyActionStatus(r.status);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setActionPending(null));
  };

  const handleCancelRestart = () => {
    setError(null);
    api.cancelRestart().then(applyActionStatus).catch((e) => setError(String(e)));
  };

  const handleSavePreset = (name: string) => {
    if (!selectedId) return;
    setError(null);
    api
      .savePreset(name, selectedId, values)
      .then((saved) => setPresets((prev) => [...prev.filter((p) => p.name !== saved.name), saved]))
      .catch((e) => setError(String(e)));
  };

  const handleLoadPreset = (preset: Preset) => {
    setSelectedId(preset.model_id);
    setValues({ ...defaultsFromSchema(schema), ...preset.flags });
    setUnsupported(preset.unsupported.length > 0 ? { preset: preset.name, keys: preset.unsupported } : null);
  };

  const binaryNotice = (() => {
    if (!binary) return null;
    if (binary.error) {
      return (
        <div className="flags-notice warn">
          <span>
            <strong>llama-server could not be probed</strong> ({binary.error}). The form below comes from a bundled
            snapshot of <code>--help</code> and may not match your build.
          </span>
        </div>
      );
    }
    return (
      <div className="muted binary-info" title={binary.resolved_path ?? undefined}>
        {describeBuild(binary)} · {schema.length} flags
      </div>
    );
  })();

  const handleDeletePreset = (name: string) => {
    setError(null);
    api
      .deletePreset(name)
      .then(() => setPresets((prev) => prev.filter((p) => p.name !== name)))
      .catch((e) => setError(String(e)));
  };

  return (
    <div className="app">
      <header>
        <h1>
          LlamaPanel {version && <span className="muted version">v{version}</span>}
        </h1>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <div className="layout">
        <section className="panel">
          <div className="panel-header">
            <h2>Models</h2>
            <button className="icon-button" disabled={modelsLoading} onClick={loadModels} title="Rescan models directory">
              {modelsLoading ? <span className="spinner" /> : "⟳"}
            </button>
          </div>
          <ModelList models={models} loading={modelsLoading} selectedId={selectedId} onSelect={setSelectedId} />
        </section>

        <section className="panel">
          <div className="panel-header">
            <h2>Flags</h2>
            {binaryNotice && !binary?.error && binaryNotice}
          </div>
          <PresetBar
            presets={presets}
            canSave={selectedId !== null}
            onLoad={handleLoadPreset}
            onSave={handleSavePreset}
            onDelete={handleDeletePreset}
          />
          {binary?.error && binaryNotice}
          {unsupported && (
            <div className="flags-notice warn">
              <span>
                Preset <strong>{unsupported.preset}</strong> has flags this llama-server build doesn't know; they are kept
                in the preset but won't be passed: <code>{unsupported.keys.join(", ")}</code>
              </span>
              <button className="link-button" onClick={() => setUnsupported(null)}>
                dismiss
              </button>
            </div>
          )}
          <FlagsForm
            schema={schema}
            values={values}
            onChange={handleFlagChange}
            loras={loras}
            modelArch={models.find((m) => m.id === selectedId)?.architecture ?? null}
          />
        </section>

        <section className="panel wide">
          <h2>Server</h2>
          <ServerControls
            status={status}
            canStart={selectedId !== null}
            pending={actionPending}
            onStart={handleStart}
            onStop={handleStop}
            onReload={handleReload}
            onCancelRestart={handleCancelRestart}
          />
          <LogViewer />
        </section>
      </div>
    </div>
  );
}
