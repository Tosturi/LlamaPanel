import type { FlagDef } from "../types";

function formatDefault(flag: FlagDef): string | null {
  if (flag.default === null || flag.default === undefined) return null;
  if (flag.type === "boolean") return flag.default ? "enabled" : "disabled";
  return String(flag.default);
}

/** A small "?" that reveals the flag's llama-server help on hover/focus:
 *  description, default, env var and every spelling the binary accepts. */
export function HelpTip({ flag }: { flag: FlagDef }) {
  const spellings = [...flag.aliases, ...flag.aliases_neg].join(", ");
  const def = formatDefault(flag);
  return (
    <span className="help-tip">
      <button type="button" className="help-tip-icon" aria-label={`Help for ${flag.cli}`}>
        ?
      </button>
      <span className="help-tip-body" role="tooltip">
        <code className="help-tip-cli">{spellings}</code>
        {flag.help && <span className="help-tip-text">{flag.help}</span>}
        <span className="help-tip-meta">
          {def !== null && (
            <span>
              default: <code>{def}</code>
            </span>
          )}
          {flag.env && (
            <span>
              env: <code>{flag.env}</code>
            </span>
          )}
          {flag.repeatable && <span>comma-separated list</span>}
        </span>
      </span>
    </span>
  );
}
