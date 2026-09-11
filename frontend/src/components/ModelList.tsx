import type { ModelInfo } from "../types";

function formatSize(bytes: number): string {
  const gb = bytes / 1024 ** 3;
  return `${gb.toFixed(1)} GB`;
}

export function ModelList({
  models,
  selectedId,
  onSelect,
}: {
  models: ModelInfo[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  if (models.length === 0) {
    return <p className="muted">No .gguf files found in the models directory.</p>;
  }

  return (
    <ul className="model-list">
      {models.map((m) => (
        <li
          key={m.id}
          className={m.id === selectedId ? "model-item selected" : "model-item"}
          onClick={() => onSelect(m.id)}
        >
          <div className="model-name">
            {m.display_name}
            {m.is_split && <span className="badge">{m.parts.length} parts</span>}
          </div>
          <div className="model-meta">
            {[m.architecture, m.file_type, formatSize(m.total_size_bytes), m.context_length ? `ctx ${m.context_length}` : null]
              .filter(Boolean)
              .join(" · ")}
          </div>
        </li>
      ))}
    </ul>
  );
}
