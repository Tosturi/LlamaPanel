import type { FlagDef, FlagValues, ModelInfo, Preset, StatusResponse } from "./types";

// Relative to the current origin: works both in Vite dev (proxied, see
// vite.config.ts) and in production, where FastAPI serves the built
// frontend and the API from the same host:port.
const BASE = "";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listModels: () => fetch(`${BASE}/api/models`).then((r) => json<ModelInfo[]>(r)),

  getFlagSchema: () => fetch(`${BASE}/api/server/flags`).then((r) => json<FlagDef[]>(r)),

  getStatus: () => fetch(`${BASE}/api/server/status`).then((r) => json<StatusResponse>(r)),

  startServer: (modelId: string, flags: FlagValues) =>
    fetch(`${BASE}/api/server/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: modelId, flags }),
    }).then((r) => json<StatusResponse>(r)),

  stopServer: () => fetch(`${BASE}/api/server/stop`, { method: "POST" }).then((r) => json<StatusResponse>(r)),

  listPresets: () => fetch(`${BASE}/api/presets`).then((r) => json<Preset[]>(r)),

  savePreset: (name: string, modelId: string, flags: FlagValues) =>
    fetch(`${BASE}/api/presets/${encodeURIComponent(name)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, model_id: modelId, flags }),
    }).then((r) => json<Preset>(r)),

  deletePreset: (name: string) =>
    fetch(`${BASE}/api/presets/${encodeURIComponent(name)}`, { method: "DELETE" }).then((r) => json(r)),

  logsSocketUrl: () => {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${window.location.host}/api/server/logs`;
  },
};
