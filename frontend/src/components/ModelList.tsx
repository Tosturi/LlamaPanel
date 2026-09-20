import type { ModelInfo } from "../types";

function formatSize(bytes: number): string {
  const gb = bytes / 1024 ** 3;
  return `${gb.toFixed(1)} GB`;
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
      <p className="muted">No models found. Check your search or the configured models directory.</p>
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
        </li>
      ))}
    </ul>
  );
}
