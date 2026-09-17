import type { ReactNode } from "react";
import type { FlagDef, FlagValues, LoraInfo } from "../types";
import { HelpTip } from "./HelpTip";

type Value = FlagValues[string];

export interface LoraSelection {
  path: string;
  scale: number;
}

function items(value: Value): string[] {
  if (value === null || value === undefined || value === "") return [];
  const list = Array.isArray(value) ? value.map((v) => (v === null ? "" : String(v))) : String(value).split(",");
  return list.map((s) => s.trim()).filter(Boolean);
}

/** The adapters currently selected, read back from the two llama-server
 *  flags: `--lora path` (scale 1) and `--lora-scaled path:scale`. Either may
 *  hold a list (one entry per adapter) or a comma-joined string typed by
 *  hand / adopted from a running process. The scale sits after the *last*
 *  colon, exactly as llama.cpp splits it, so `C:\...` paths survive. */
export function parseLoraSelection(lora: Value, loraScaled: Value): LoraSelection[] {
  const out: LoraSelection[] = [];
  for (const path of items(lora)) out.push({ path, scale: 1 });
  for (const item of items(loraScaled)) {
    const cut = item.lastIndexOf(":");
    const scale = cut > 0 ? Number(item.slice(cut + 1)) : NaN;
    if (cut > 0 && Number.isFinite(scale)) out.push({ path: item.slice(0, cut), scale });
    else out.push({ path: item, scale: 1 });
  }
  return out;
}

/** Inverse of parseLoraSelection: scale 1 goes to --lora, anything else to
 *  --lora-scaled. Empty lists become null so the flags read as unset. */
export function toLoraValues(selection: LoraSelection[]): { lora: string[] | null; lora_scaled: string[] | null } {
  const lora = selection.filter((s) => s.scale === 1).map((s) => s.path);
  const scaled = selection.filter((s) => s.scale !== 1).map((s) => `${s.path}:${s.scale}`);
  return { lora: lora.length ? lora : null, lora_scaled: scaled.length ? scaled : null };
}

function formatSize(bytes: number): string {
  const mb = bytes / 1024 ** 2;
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.max(1, Math.round(mb))} MB`;
}

function ScaleInput({ value, onChange }: { value: number; onChange: (scale: number) => void }) {
  return (
    <label className="lora-scale" title="Adapter scale (1 = as trained)">
      ×
      <input
        type="number"
        step="0.1"
        value={value}
        onChange={(e) => {
          const n = Number(e.target.value);
          if (e.target.value !== "" && Number.isFinite(n)) onChange(n);
        }}
      />
    </label>
  );
}

/** Multi-select over the LoRA adapters found in the models directory,
 *  writing the choice into the `lora` / `lora_scaled` flags so presets,
 *  build_args and process adoption keep working unchanged. Adapters whose
 *  architecture differs from the selected model are still selectable but
 *  marked: llama-server refuses to apply them at startup. */
export function LoraPicker({
  loras,
  modelArch,
  loraFlag,
  scaledFlag,
  values,
  onChange,
  children,
}: {
  loras: LoraInfo[];
  modelArch: string | null;
  loraFlag: FlagDef;
  scaledFlag: FlagDef | undefined;
  values: FlagValues;
  onChange: (key: string, value: Value) => void;
  children?: ReactNode;
}) {
  const selection = parseLoraSelection(values[loraFlag.key], scaledFlag ? values[scaledFlag.key] : null);
  const byPath = new Map(selection.map((s) => [s.path, s]));

  const apply = (next: LoraSelection[]) => {
    const v = toLoraValues(next);
    if (scaledFlag) {
      onChange(loraFlag.key, v.lora);
      onChange(scaledFlag.key, v.lora_scaled);
    } else {
      // Build without --lora-scaled: everything has to go through --lora.
      onChange(loraFlag.key, next.length ? next.map((s) => s.path) : null);
    }
  };
  const toggle = (path: string, on: boolean) =>
    apply(on ? [...selection, { path, scale: 1 }] : selection.filter((s) => s.path !== path));
  const setScale = (path: string, scale: number) => apply(selection.map((s) => (s.path === path ? { ...s, scale } : s)));

  // Selected paths the scan doesn't know (typed by hand, another machine's
  // preset, an adapter removed from disk): shown so they can be dropped.
  const known = new Set(loras.map((l) => l.path));
  const custom = selection.filter((s) => !known.has(s.path));

  return (
    <fieldset className="lora-picker">
      <legend>
        LoRA adapters
        {selection.length > 0 && <span className="changed-count">{selection.length} selected</span>}
        <HelpTip flag={loraFlag} />
      </legend>

      {loras.length === 0 && custom.length === 0 && (
        <p className="muted">
          No adapters found. Put LoRA <code>.gguf</code> files next to the models or into a <code>loras/</code> subfolder.
        </p>
      )}

      {loras.map((l) => {
        const selected = byPath.get(l.path);
        const mismatch = Boolean(modelArch && l.architecture && l.architecture !== modelArch);
        const meta = [l.base_model, l.architecture, formatSize(l.size_bytes)].filter(Boolean).join(" · ");
        return (
          <div key={l.path} className={`lora-item${selected ? " changed" : ""}${mismatch ? " incompatible" : ""}`}>
            <label className="lora-label" title={l.path}>
              <input type="checkbox" checked={Boolean(selected)} onChange={(e) => toggle(l.path, e.target.checked)} />
              <span className="lora-name">{l.display_name}</span>
              <span className="lora-meta">{meta}</span>
            </label>
            {mismatch && (
              <span className="lora-warn" title={`Built for ${l.architecture}; the selected model is ${modelArch}`}>
                for {l.architecture}
              </span>
            )}
            {selected && <ScaleInput value={selected.scale} onChange={(scale) => setScale(l.path, scale)} />}
          </div>
        );
      })}

      {custom.map((s) => (
        <div key={s.path} className="lora-item changed custom">
          <span className="lora-label" title={s.path}>
            <span className="lora-name">{s.path}</span>
            <span className="lora-meta">not in models directory</span>
          </span>
          <ScaleInput value={s.scale} onChange={(scale) => setScale(s.path, scale)} />
          <button type="button" className="flag-reset" title="Remove" onClick={() => toggle(s.path, false)}>
            ×
          </button>
        </div>
      ))}

      {children}
    </fieldset>
  );
}
