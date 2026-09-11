import type { FlagDef, FlagValues } from "../types";

function FlagInput({ flag, value, onChange }: { flag: FlagDef; value: unknown; onChange: (v: any) => void }) {
  switch (flag.type) {
    case "boolean":
      return (
        <label className="flag-row checkbox">
          <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
          {flag.label}
        </label>
      );
    case "enum":
      return (
        <label className="flag-row">
          {flag.label}
          <select value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value || null)}>
            <option value="">(default)</option>
            {flag.options?.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </label>
      );
    case "number":
      return (
        <label className="flag-row">
          {flag.label}
          <input
            type="number"
            value={(value as number) ?? ""}
            onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
          />
        </label>
      );
    default:
      return (
        <label className="flag-row">
          {flag.label}
          <input type="text" value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value || null)} />
        </label>
      );
  }
}

export function FlagsForm({
  schema,
  values,
  onChange,
}: {
  schema: FlagDef[];
  values: FlagValues;
  onChange: (key: string, value: unknown) => void;
}) {
  const basic = schema.filter((f) => f.group === "basic");
  const advanced = schema.filter((f) => f.group === "advanced");

  return (
    <div className="flags-form">
      <fieldset>
        <legend>Basic</legend>
        {basic.map((f) => (
          <FlagInput key={f.key} flag={f} value={values[f.key]} onChange={(v) => onChange(f.key, v)} />
        ))}
      </fieldset>
      <details>
        <summary>Advanced</summary>
        <fieldset>
          {advanced.map((f) => (
            <FlagInput key={f.key} flag={f} value={values[f.key]} onChange={(v) => onChange(f.key, v)} />
          ))}
        </fieldset>
      </details>
    </div>
  );
}
