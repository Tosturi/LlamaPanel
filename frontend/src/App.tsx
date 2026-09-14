import { useEffect, useState } from "react";
import { api } from "./api";
import { FlagsForm } from "./components/FlagsForm";
import { LogViewer } from "./components/LogViewer";
import { ModelList } from "./components/ModelList";
import { PresetBar } from "./components/PresetBar";
import { ServerControls } from "./components/ServerControls";
import type { FlagDef, FlagValues, ModelInfo, Preset, StatusResponse } from "./types";

function defaultsFromSchema(schema: FlagDef[]): FlagValues {
  const values: FlagValues = {};
  for (const f of schema) values[f.key] = f.default ?? null;
  return values;
}

export default function App() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [schema, setSchema] = useState<FlagDef[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [values, setValues] = useState<FlagValues>({});
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [syncedPid, setSyncedPid] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [actionPending, setActionPending] = useState<"start" | "stop" | null>(null);

  const loadModels = () => {
    setModelsLoading(true);
    return api.listModels().then(setModels).catch((e) => setError(String(e))).finally(() => setModelsLoading(false));
  };

  useEffect(() => {
    loadModels();
    api.listPresets().then(setPresets).catch((e) => setError(String(e)));
    api.getFlagSchema().then((s) => {
      setSchema(s);
      setValues(defaultsFromSchema(s));
    }).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    const poll = () => api.getStatus().then(setStatus).catch(() => {});
    poll();
    const id = setInterval(poll, 5000);
    return () => clearInterval(id);
  }, []);

  // If a llama-server is already running (started manually, or left over
  // from a previous panel session) pull its model + flags into the form
  // instead of showing an empty/stale UI. Only re-syncs when the running
  // pid actually changes, so it won't fight the user editing a new config
  // while nothing is running.
  useEffect(() => {
    if (!status || schema.length === 0) return;
    if (status.pid === null) {
      setSyncedPid(null);
      return;
    }
    const isLive = status.state === "running" || status.state === "starting";
    if (isLive && status.pid !== syncedPid) {
      setSyncedPid(status.pid);
      if (status.model_id) setSelectedId(status.model_id);
      setValues({ ...defaultsFromSchema(schema), ...(status.flags ?? {}) });
    }
  }, [status, schema, syncedPid]);

  const handleFlagChange = (key: string, value: unknown) => {
    setValues((prev) => ({ ...prev, [key]: value as FlagValues[string] }));
  };

  const handleStart = () => {
    if (!selectedId) return;
    setError(null);
    setActionPending("start");
    api.startServer(selectedId, values).then(setStatus).catch((e) => setError(String(e))).finally(() => setActionPending(null));
  };

  const handleStop = () => {
    setError(null);
    setActionPending("stop");
    api.stopServer().then(setStatus).catch((e) => setError(String(e))).finally(() => setActionPending(null));
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
  };

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
        <h1>LlamaPanel</h1>
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
          <h2>Flags</h2>
          <PresetBar
            presets={presets}
            canSave={selectedId !== null}
            onLoad={handleLoadPreset}
            onSave={handleSavePreset}
            onDelete={handleDeletePreset}
          />
          <FlagsForm schema={schema} values={values} onChange={handleFlagChange} />
        </section>

        <section className="panel wide">
          <h2>Server</h2>
          <ServerControls
            status={status}
            canStart={selectedId !== null}
            pending={actionPending}
            onStart={handleStart}
            onStop={handleStop}
          />
          <LogViewer />
        </section>
      </div>
    </div>
  );
}
