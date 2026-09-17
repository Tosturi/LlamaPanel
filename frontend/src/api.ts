import type {
  BinaryInfo,
  DeletedResponse,
  FlagDef,
  FlagValues,
  HealthResponse,
  ModelInfo,
  Preset,
  RestartResponse,
  StartRequest,
  StatusResponse,
} from "./types";

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

function post<T>(path: string, body?: unknown): Promise<T> {
  return fetch(`${BASE}${path}`, {
    method: "POST",
    ...(body !== undefined && {
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  }).then((r) => json<T>(r));
}

export const api = {
  getHealth: () => fetch(`${BASE}/api/health`).then((r) => json<HealthResponse>(r)),

  listModels: () => fetch(`${BASE}/api/models`).then((r) => json<ModelInfo[]>(r)),

  getFlagSchema: () => fetch(`${BASE}/api/server/flags`).then((r) => json<FlagDef[]>(r)),

  getBinaryInfo: () => fetch(`${BASE}/api/server/binary`).then((r) => json<BinaryInfo>(r)),

  getStatus: () => fetch(`${BASE}/api/server/status`).then((r) => json<StatusResponse>(r)),

  startServer: (modelId: string, flags: FlagValues) => {
    const body: StartRequest = { model_id: modelId, flags };
    return post<StatusResponse>("/api/server/start", body);
  },

  stopServer: () => post<StatusResponse>("/api/server/stop"),

  restartServer: (modelId: string, flags: FlagValues) => {
    const body: StartRequest = { model_id: modelId, flags };
    return post<RestartResponse>("/api/server/restart", body);
  },

  cancelRestart: () => post<StatusResponse>("/api/server/restart/cancel"),

  listPresets: () => fetch(`${BASE}/api/presets`).then((r) => json<Preset[]>(r)),

  savePreset: (name: string, modelId: string, flags: FlagValues) => {
    // `unsupported` is computed by the server on read and ignored on input.
    const body: Preset = { name, model_id: modelId, flags, unsupported: [] };
    return fetch(`${BASE}/api/presets/${encodeURIComponent(name)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => json<Preset>(r));
  },

  deletePreset: (name: string) =>
    fetch(`${BASE}/api/presets/${encodeURIComponent(name)}`, { method: "DELETE" }).then((r) =>
      json<DeletedResponse>(r),
    ),

  logsSocketUrl: () => {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${window.location.host}/api/server/logs`;
  },
};
