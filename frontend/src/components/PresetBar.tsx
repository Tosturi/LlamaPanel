import { useState } from "react";
import type { Preset } from "../types";

export function PresetBar({
  presets,
  canSave,
  onLoad,
  onSave,
}: {
  presets: Preset[];
  canSave: boolean;
  onLoad: (preset: Preset) => void;
  onSave: (name: string) => void;
}) {
  const [name, setName] = useState("");
  const [selectedName, setSelectedName] = useState("");
  const selectedPreset = presets.find((preset) => preset.name === selectedName);

  return (
    <div className="preset-bar">
      <div className="preset-load">
        <select
          aria-label="Preset to load"
          value={selectedPreset ? selectedName : ""}
          onChange={(e) => setSelectedName(e.target.value)}
        >
          <option value="" disabled>
            Select a preset…
          </option>
          {presets.map((p) => (
            <option key={p.name} value={p.name}>
              {p.name}
            </option>
          ))}
        </select>
        <button
          type="button"
          disabled={!selectedPreset}
          onClick={() => {
            if (selectedPreset) onLoad(selectedPreset);
          }}
        >
          Load preset
        </button>
      </div>

      <input
        aria-label="New preset name"
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
        title={
          canSave
            ? "Save current model + flags as a preset"
            : "Select a model first"
        }
        onClick={() => {
          onSave(name.trim());
          setName("");
        }}
      >
        Save as preset
      </button>
    </div>
  );
}
