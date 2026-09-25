import type { FlagValues } from "./types";

/** Port belongs to the instance; unset values do not emit arguments. */
export function samePresetFlags(a: FlagValues, b: FlagValues): boolean {
  const normalized = (flags: FlagValues) => Object.entries(flags)
    .filter(([key, value]) => key !== "port" && value != null && value !== "" &&
      (!Array.isArray(value) || value.length > 0))
    .sort(([a], [b]) => a.localeCompare(b));
  return JSON.stringify(normalized(a)) === JSON.stringify(normalized(b));
}
