import { useState } from "react";
import type { Preset } from "../types";

export function PresetBar({
  presets,
  canSave,
  onLoad,
  onSave,
  onDelete,
}: {
  presets: Preset[];
  canSave: boolean;
  onLoad: (preset: Preset) => void;
  onSave: (name: string) => void;
  onDelete: (name: string) => void;
}) {
  const [name, setName] = useState("");

  return (
    <div className="preset-bar">
      <select
        defaultValue=""
        onChange={(e) => {
          const preset = presets.find((p) => p.name === e.target.value);
          if (preset) onLoad(preset);
          e.target.value = "";
        }}
      >
        <option value="" disabled>
          Load preset...
        </option>
        {presets.map((p) => (
          <option key={p.name} value={p.name}>
            {p.name}
          </option>
        ))}
      </select>

      <input
        placeholder="preset name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && name.trim() && canSave) {
            onSave(name.trim());
            setName("");
          }
        }}
      />
      <button
        disabled={!name.trim() || !canSave}
        title={canSave ? "Save current model + flags as a preset" : "Select a model first"}
        onClick={() => {
          onSave(name.trim());
          setName("");
        }}
      >
        Save as preset
      </button>

      {presets.length > 0 && (
        <select
          defaultValue=""
          title="Delete a preset"
          onChange={(e) => {
            if (e.target.value) onDelete(e.target.value);
            e.target.value = "";
          }}
        >
          <option value="" disabled>
            Delete preset...
          </option>
          {presets.map((p) => (
            <option key={p.name} value={p.name}>
              {p.name}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
