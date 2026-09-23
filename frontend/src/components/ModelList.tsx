import { useEffect, useRef, useState } from "react";
import type { ModelInfo } from "../types";

function ModelDetails({ model: m, onClose }: { model: ModelInfo; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const close = () => { dialog.current?.close(); onClose(); };
  useEffect(() => {
    const element = dialog.current!;
    element.showModal();
    return () => element.close();
  }, []);
  return <dialog ref={dialog} className="panel model-dialog" aria-labelledby="model-details-title"
    onCancel={e => { e.preventDefault(); close(); }}>
    <div className="panel-header">
      <h2 id="model-details-title">{m.display_name}</h2>
      <button type="button" onClick={close} autoFocus>Close</button>
    </div>
    <dl className="details-list">
      <div><dt>Metadata name (general.name)</dt><dd>{m.metadata_name || "Not available"}</dd></div>
      <div><dt>Architecture</dt><dd>{m.architecture ?? "Not available"}</dd></div>
      <div><dt>Quantization</dt><dd>{m.file_type ?? "Not available"}</dd></div>
      <div><dt>Context length</dt><dd>{m.context_length ?? "Not available"}</dd></div>
      <div><dt>Total file size</dt><dd>{formatSize(m.total_size_bytes)}</dd></div>
    </dl>
    <p className="muted">Metadata is read from the {m.is_split ? "first part" : "GGUF header"}; values may be missing or inaccurate.</p>
    <p className="muted">Entry file</p>
    <code className="file-path">{m.entry_path}</code>
    {m.is_split && <>
      <p className="muted">Parts ({m.parts.length})</p>
      <ul>{m.parts.map(part => <li key={part.path}><code>{part.filename}</code></li>)}</ul>
    </>}
  </dialog>;
}

function formatSize(bytes: number): string {
  const gb = bytes / 1024 ** 3;
  return `${gb.toFixed(1)} GiB`;
}

export function ModelList({
  models,
  loading,
  selectedId,
  onSelect,
}: {
  models: ModelInfo[];
  loading: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const [details, setDetails] = useState<ModelInfo | null>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const closeDetails = () => { setDetails(null); trigger.current?.focus(); };
  if (loading) {
    return (
      <p className="muted">
        <span className="spinner" /> Scanning models directory…
      </p>
    );
  }

  if (models.length === 0) {
    return (
      <p className="muted">
        No models found. Check your search or the configured models directory.
      </p>
    );
  }

  return (
    <>
    <ul className="model-list library-grid">
      {models.map((m) => (
        <li
          key={m.id}
          className={m.id === selectedId ? "model-item selected" : "model-item"}
        >
          <button
            className="model-select"
            aria-pressed={m.id === selectedId}
            onClick={() => onSelect(m.id)}
          >
            <div className="eyebrow">GGUF model</div>
            <div className="model-name">
              {m.display_name}
              {m.is_split && (
                <span className="badge">{m.parts.length} parts</span>
              )}
            </div>
            <div className="model-meta">
              {[
                m.architecture,
                m.file_type,
                formatSize(m.total_size_bytes),
                m.context_length ? `ctx ${m.context_length}` : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </div>
            <span className="model-cta">Configure server →</span>
          </button>
          <div className="model-details-action">
            <button type="button" aria-haspopup="dialog" onClick={e => {
              trigger.current = e.currentTarget; setDetails(m);
            }}>Metadata & files</button>
          </div>
        </li>
      ))}
    </ul>
    {details && <ModelDetails model={details} onClose={closeDetails} />}
    </>
  );
}
