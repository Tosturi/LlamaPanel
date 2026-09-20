import type { ModelInfo } from "../types";

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
          <details className="model-details">
            <summary>Metadata & files</summary>
            <dl className="details-list">
              <div>
                <dt>Metadata name (general.name)</dt>
                <dd>{m.metadata_name || "Not available"}</dd>
              </div>
              <div>
                <dt>Architecture</dt>
                <dd>{m.architecture ?? "Not available"}</dd>
              </div>
              <div>
                <dt>Quantization</dt>
                <dd>{m.file_type ?? "Not available"}</dd>
              </div>
              <div>
                <dt>Context length</dt>
                <dd>{m.context_length ?? "Not available"}</dd>
              </div>
              <div>
                <dt>Total file size</dt>
                <dd>{formatSize(m.total_size_bytes)}</dd>
              </div>
            </dl>
            <p className="muted">
              Metadata is read from the{" "}
              {m.is_split ? "first part" : "GGUF header"}; values may be missing
              or inaccurate.
            </p>
            <p className="muted">Entry file</p>
            <code className="file-path">{m.entry_path}</code>
            {m.is_split && (
              <>
                <p className="muted">Parts ({m.parts.length})</p>
                <ul>
                  {m.parts.map((part) => (
                    <li key={part.path}>
                      <code>{part.filename}</code>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </details>
        </li>
      ))}
    </ul>
  );
}
