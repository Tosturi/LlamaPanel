import { useMemo, useState } from "react";
import type { FlagDef, FlagValues, LoraInfo } from "../types";
import { HelpTip } from "./HelpTip";
import { LoraPicker } from "./LoraPicker";

type Value = FlagValues[string];

// llama.cpp section names -> what the panel calls them, in display order.
const SECTIONS: [string, string][] = [
  ["common params", "Common"],
  ["example-specific params", "Server"],
  ["sampling params", "Sampling"],
  ["speculative params", "Speculative decoding"],
];

function sectionTitle(section: string): string {
  return SECTIONS.find(([s]) => s === section)?.[1] ?? section;
}

/** Whether the value would make it onto the command line, i.e. is set
 *  and differs from the flag's documented default. Mirrors build_args. */
export function isChanged(flag: FlagDef, value: Value): boolean {
  if (value === null || value === undefined || value === "") return false;
  if (Array.isArray(value)) return value.length > 0;
  if (flag.type === "boolean") {
    if (flag.default === null || flag.default === undefined) return true;
    return Boolean(value) !== Boolean(flag.default);
  }
  if (flag.default === null || flag.default === undefined) return true;
  return String(value) !== String(flag.default);
}

function textValue(value: Value): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.filter((v) => v !== null).join(",");
  return String(value);
}

function FlagInput({ flag, value, onChange }: { flag: FlagDef; value: Value; onChange: (v: Value) => void }) {
  const id = `flag-${flag.key}`;
  switch (flag.type) {
    case "boolean":
      return (
        <input
          id={id}
          type="checkbox"
          checked={Boolean(value)}
          onChange={(e) => onChange(e.target.checked)}
        />
      );
    case "enum":
      return (
        <select id={id} value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value || null)}>
          <option value="">(default)</option>
          {flag.options?.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      );
    case "number":
      return (
        <input
          id={id}
          type="number"
          step="any"
          value={typeof value === "number" ? value : ""}
          placeholder={flag.default !== null ? String(flag.default) : ""}
          onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        />
      );
    default:
      return (
        <input
          id={id}
          type="text"
          value={textValue(value)}
          placeholder={
            flag.default !== null ? String(flag.default) : flag.type === "path" ? "path" : flag.repeatable ? "a,b,c" : ""
          }
          onChange={(e) => onChange(e.target.value || null)}
        />
      );
  }
}

function FlagRow({ flag, value, onChange }: { flag: FlagDef; value: Value; onChange: (v: Value) => void }) {
  const changed = isChanged(flag, value);
  const showCli = flag.label !== flag.cli;
  return (
    <div className={`flag-row${changed ? " changed" : ""}${flag.type === "boolean" ? " checkbox" : ""}`}>
      <label className="flag-label" htmlFor={`flag-${flag.key}`}>
        {flag.type === "boolean" && <FlagInput flag={flag} value={value} onChange={onChange} />}
        <span className="flag-name">{flag.label}</span>
        {showCli && <code className="flag-cli">{flag.cli}</code>}
      </label>
      <span className="flag-controls">
        {flag.type !== "boolean" && <FlagInput flag={flag} value={value} onChange={onChange} />}
        {changed && (
          <button
            type="button"
            className="flag-reset"
            title={`Reset to default${flag.default !== null ? ` (${String(flag.default)})` : ""}`}
            onClick={() => onChange(flag.default ?? null)}
          >
            ×
          </button>
        )}
        <HelpTip flag={flag} />
      </span>
    </div>
  );
}

const bySpelling = (schema: FlagDef[], cli: string) => schema.find((f) => f.aliases.includes(cli));

/** The flags the LoRA picker takes over from the generic rows, when the
 *  build has them. Matched by spelling, so a renamed key still finds them. */
function loraFlags(schema: FlagDef[]) {
  const lora = bySpelling(schema, "--lora");
  if (!lora) return null;
  return { lora, scaled: bySpelling(schema, "--lora-scaled"), initOnly: bySpelling(schema, "--lora-init-without-apply") };
}

function matches(flag: FlagDef, needle: string): boolean {
  const haystack = [flag.key, flag.cli, flag.label, flag.help ?? "", ...flag.aliases, ...flag.aliases_neg, flag.env ?? ""]
    .join(" ")
    .toLowerCase();
  return needle.split(/\s+/).every((word) => haystack.includes(word));
}

export function FlagsForm({
  schema,
  values,
  onChange,
  loras = [],
  modelArch = null,
}: {
  schema: FlagDef[];
  values: FlagValues;
  onChange: (key: string, value: Value) => void;
  loras?: LoraInfo[];
  modelArch?: string | null;
}) {
  const [query, setQuery] = useState("");
  const needle = query.trim().toLowerCase();

  const lora = useMemo(() => loraFlags(schema), [schema]);
  // Rendered by the picker instead of as plain rows (search still lists them).
  const pickerKeys = useMemo(
    () => new Set([lora?.lora.key, lora?.scaled?.key, lora?.initOnly?.key].filter((k): k is string => Boolean(k))),
    [lora],
  );
  const basic = useMemo(() => schema.filter((f) => f.group === "basic" && !pickerKeys.has(f.key)), [schema, pickerKeys]);
  const sections = useMemo(() => {
    const order = new Map<string, FlagDef[]>();
    for (const [name] of SECTIONS) order.set(name, []);
    for (const f of schema) {
      if (f.group === "basic" || pickerKeys.has(f.key)) continue;
      if (!order.has(f.section)) order.set(f.section, []);
      order.get(f.section)!.push(f);
    }
    return [...order.entries()].filter(([, flags]) => flags.length > 0);
  }, [schema, pickerKeys]);

  const changedCount = (flags: FlagDef[]) => flags.filter((f) => isChanged(f, values[f.key])).length;
  const row = (f: FlagDef) => <FlagRow key={f.key} flag={f} value={values[f.key]} onChange={(v) => onChange(f.key, v)} />;

  if (schema.length === 0) return <p className="muted">Loading flags…</p>;

  return (
    <div className="flags-form">
      <input
        type="search"
        className="flag-search"
        placeholder={`Search ${schema.length} flags…`}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />

      {needle ? (
        <fieldset>
          {schema.filter((f) => matches(f, needle)).map(row)}
          {!schema.some((f) => matches(f, needle)) && <p className="muted">No flags match “{query}”.</p>}
        </fieldset>
      ) : (
        <>
          <fieldset>
            <legend>Basic</legend>
            {basic.map(row)}
          </fieldset>
          {lora && (
            <LoraPicker
              loras={loras}
              modelArch={modelArch}
              loraFlag={lora.lora}
              scaledFlag={lora.scaled}
              values={values}
              onChange={onChange}
            >
              {lora.initOnly && row(lora.initOnly)}
            </LoraPicker>
          )}
          {sections.map(([section, flags]) => {
            const changed = changedCount(flags);
            return (
              <details key={section} className="flag-section">
                <summary>
                  <span>{sectionTitle(section)}</span>
                  <span className="muted">
                    {changed > 0 && <span className="changed-count">{changed} set</span>}
                    {flags.length}
                  </span>
                </summary>
                <fieldset>{flags.map(row)}</fieldset>
              </details>
            );
          })}
        </>
      )}
    </div>
  );
}
