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

/** An explicit override, including a value equal to the documented default. */
export function isChanged(flag: FlagDef, value: Value): boolean {
  if (value === null || value === undefined || value === "") return false;
  if (Array.isArray(value)) return value.length > 0;
  return flag.type !== "boolean" || Boolean(value) || Boolean(flag.cli_neg);
}

function textValue(value: Value): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.filter((v) => v !== null).join(",");
  return String(value);
}

function FlagInput({
  flag,
  value,
  onChange,
}: {
  flag: FlagDef;
  value: Value;
  onChange: (v: Value) => void;
}) {
  const id = `flag-${flag.key}`;
  switch (flag.type) {
    case "boolean":
      return (
        <select
          id={id}
          value={value === true ? "true" : value === false ? "false" : ""}
          onChange={(e) =>
            onChange(e.target.value === "" ? null : e.target.value === "true")
          }
        >
          <option value="">Server default</option>
          <option value="true">Enabled</option>
          {flag.cli_neg && <option value="false">Disabled</option>}
        </select>
      );
    case "enum":
      return (
        <select
          id={id}
          value={(value as string) ?? ""}
          onChange={(e) => onChange(e.target.value || null)}
        >
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
          onChange={(e) =>
            onChange(e.target.value === "" ? null : Number(e.target.value))
          }
        />
      );
    default:
      return (
        <input
          id={id}
          type="text"
          value={textValue(value)}
          placeholder={
            flag.default !== null
              ? String(flag.default)
              : flag.type === "path"
                ? "path"
                : flag.repeatable
                  ? "a,b,c"
                  : ""
          }
          onChange={(e) => onChange(e.target.value || null)}
        />
      );
  }
}

function FlagRow({
  flag,
  value,
  onChange,
}: {
  flag: FlagDef;
  value: Value;
  onChange: (v: Value) => void;
}) {
  const changed = isChanged(flag, value);
  const showCli = flag.label !== flag.cli;
  return (
    <div
      className={`flag-row${changed ? " changed" : ""}${flag.type === "boolean" ? " checkbox" : ""}`}
    >
      <label className="flag-label" htmlFor={`flag-${flag.key}`}>
        <span className="flag-name">{flag.label}</span>
        {showCli && <code className="flag-cli">{flag.cli}</code>}
      </label>
      <span className="flag-controls">
        <FlagInput flag={flag} value={value} onChange={onChange} />
        {changed && (
          <button
            type="button"
            className="flag-reset"
            title="Use server default (omit flag)"
            aria-label={`Reset ${flag.label}`}
            onClick={() => onChange(null)}
          >
            ×
          </button>
        )}
        <HelpTip flag={flag} />
      </span>
    </div>
  );
}

const bySpelling = (schema: FlagDef[], cli: string) =>
  schema.find((f) => f.aliases.includes(cli));

/** The flags the LoRA picker takes over from the generic rows, when the
 *  build has them. Matched by spelling, so a renamed key still finds them. */
function loraFlags(schema: FlagDef[]) {
  const lora = bySpelling(schema, "--lora");
  if (!lora) return null;
  return {
    lora,
    scaled: bySpelling(schema, "--lora-scaled"),
    initOnly: bySpelling(schema, "--lora-init-without-apply"),
  };
}

function matches(flag: FlagDef, needle: string): boolean {
  const haystack = [
    flag.key,
    flag.cli,
    flag.label,
    flag.help ?? "",
    ...flag.aliases,
    ...flag.aliases_neg,
    flag.env ?? "",
  ]
    .join(" ")
    .toLowerCase();
  return needle.split(/\s+/).every((word) => haystack.includes(word));
}

export function FlagsForm({
  schema,
  values,
  onChange,
  onClear,
  loras = [],
  modelArch = null,
}: {
  schema: FlagDef[];
  values: FlagValues;
  onChange: (key: string, value: Value) => void;
  onClear: () => void;
  loras?: LoraInfo[];
  modelArch?: string | null;
}) {
  const [query, setQuery] = useState("");
  const [activeOnly, setActiveOnly] = useState(false);
  const needle = query.trim().toLowerCase();

  const lora = useMemo(() => loraFlags(schema), [schema]);
  // Rendered by the picker instead of as plain rows (search still lists them).
  const pickerKeys = useMemo(
    () =>
      new Set(
        [lora?.lora.key, lora?.scaled?.key, lora?.initOnly?.key].filter(
          (k): k is string => Boolean(k),
        ),
      ),
    [lora],
  );
  const basic = useMemo(
    () => schema.filter((f) => f.group === "basic" && !pickerKeys.has(f.key)),
    [schema, pickerKeys],
  );
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

  const changedCount = (flags: FlagDef[]) =>
    flags.filter((f) => isChanged(f, values[f.key])).length;
  const row = (f: FlagDef) => (
    <FlagRow
      key={f.key}
      flag={f}
      value={values[f.key]}
      onChange={(v) => onChange(f.key, v)}
    />
  );

  if (schema.length === 0) return <p className="muted">Loading flags…</p>;

  return (
    <div className="flags-form">
      <div className="panel-header">
        <label>
          <input
            type="checkbox"
            checked={activeOnly}
            onChange={(e) => setActiveOnly(e.target.checked)}
          />{" "}
          Only explicit flags (
          {schema.filter((f) => isChanged(f, values[f.key])).length})
        </label>
        <button
          type="button"
          onClick={onClear}
          disabled={!Object.keys(values).length}
        >
          Clear all overrides
        </button>
      </div>
      <p className="muted">
        Empty fields use llama-server defaults. Hints are informational; only
        explicitly set values are sent. Presets and adopted processes may
        contain earlier overrides.
      </p>
      <input
        type="search"
        className="flag-search"
        placeholder={`Search ${schema.length} flags…`}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />

      {needle || activeOnly ? (
        <fieldset>
          {schema
            .filter(
              (f) =>
                matches(f, needle) &&
                (!activeOnly || isChanged(f, values[f.key])),
            )
            .map(row)}
          {!schema.some(
            (f) =>
              matches(f, needle) &&
              (!activeOnly || isChanged(f, values[f.key])),
          ) && <p className="muted">No flags match “{query}”.</p>}
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
                    {changed > 0 && (
                      <span className="changed-count">{changed} set</span>
                    )}
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
