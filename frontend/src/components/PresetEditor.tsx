import { useState } from "react";
import { FlagsForm } from "./FlagsForm";
import type { FlagDef, FlagValues, LoraInfo, ModelInfo, Preset } from "../types";

export function PresetEditor({ preset, schema, models, loras, onSave, onCancel }: {
  preset: Preset;
  schema: FlagDef[];
  models: ModelInfo[];
  loras: LoraInfo[];
  onSave: (preset: Preset) => Promise<void>;
  onCancel: () => void;
}) {
  const [name, setName] = useState(preset.name);
  const [values, setValues] = useState<FlagValues>({ ...preset.flags });
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const model = models.find(m => m.id === preset.model_id);
  const unknown = Object.keys(values).filter(key => !schema.some(f => f.key === key));
  const change = (key: string, value: FlagValues[string]) => setValues(prev => {
    const next = { ...prev };
    if (value == null || value === "" || (Array.isArray(value) && !value.length)) delete next[key];
    else next[key] = value;
    return next;
  });
  const save = async () => {
    if (pending || !name.trim()) return;
    setPending(true); setError("");
    try { await onSave({ ...preset, name: name.trim(), flags: values }); }
    catch (e) { setError(String(e)); }
    finally { setPending(false); }
  };
  return <section className="panel preset-editor" aria-label="Edit preset">
    <div className="panel-header"><h2>Edit preset</h2></div>
    <p className="muted">Model: {model?.display_name ?? preset.model_id}. Saving updates this shared preset. Load it into a server to use the changes.</p>
    {error && <p className="error-banner" role="alert">{error}</p>}
    <fieldset disabled={pending} className="preset-editor-fields">
      <label>Preset name
        <input autoFocus value={name} onChange={e => setName(e.target.value)} />
      </label>
      {unknown.length > 0 && <div className="flags-notice warn">
        <p>Flags outside this runtime's form are preserved unless removed:</p>
        {unknown.map(key => <div key={key}>
          <code>{key}: {JSON.stringify(values[key])}</code>{" "}
          <button type="button" onClick={() => change(key, null)} aria-label={`Remove ${key}`}>Remove</button>
        </div>)}
      </div>}
      <FlagsForm schema={schema} values={values} onChange={change}
        onClear={() => setValues({})} loras={loras} modelArch={model?.architecture ?? null} />
    </fieldset>
    <div className="preset-editor-actions">
      <button type="button" className="primary" disabled={pending || !name.trim()} onClick={save}>
        {pending ? "Saving…" : "Save changes"}
      </button>
      <button type="button" disabled={pending} onClick={onCancel}>Cancel</button>
    </div>
  </section>;
}
