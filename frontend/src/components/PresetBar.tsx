import { useState } from "react";
import type { Preset } from "../types";

export function PresetBar({
  presets,
  canSave,
  onLoad,
  onSave, name, onNameChange, loadedName, canUpdate, onUpdate, pending,
}: {
  name: string;
  onNameChange: (name: string) => void;
  loadedName: string | null;
  canUpdate: boolean;
  onUpdate: () => void;
  pending: boolean;
  presets: Preset[];
  canSave: boolean;
  onLoad: (preset: Preset) => void;
  onSave: (name: string) => void;
}) {
  const [selectedName, setSelectedName] = useState("");
  const nameTaken = presets.some(p => p.name === name.trim());
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
          disabled={!selectedPreset || pending}
          onClick={() => {
            if (selectedPreset) onLoad(selectedPreset);
          }}
        >
          Load preset
        </button>
      </div>

      <input
        aria-label="Preset name"
        placeholder="preset name"
        value={name}
        disabled={pending}
        onChange={(e) => onNameChange(e.target.value)}
      />
      <button
        disabled={!name.trim() || !canSave || nameTaken || pending}
        title={
          canSave
            ? nameTaken ? "Choose a different name for the new preset" : "Save current model + flags as a new preset"
            : "Select a model first"
        }
        onClick={() => onSave(name.trim())}
      >
        Save as a new preset
      </button>
      <button disabled={!loadedName || !canUpdate || !name.trim() || !canSave || pending}
        title={loadedName ? `Update preset “${loadedName}”` : "Load a preset to edit it"}
        onClick={onUpdate}>Save changes</button>
      {nameTaken && <p className="muted preset-name-hint">Use a different name to save a new preset.</p>}
    </div>
  );
}
