import type {
  BinaryInfo,
  DeletedResponse,
  FlagDef,
  FlagValues,
  HealthResponse,
  LoraInfo,
  ModelInfo,
  Preset,
  RestartResponse,
  StartRequest,
  StatusResponse,
  InstanceView,
  InstanceConfig,
  SettingsView,
  SettingsUpdate,
  BrowserView,
  NativePickerView,
  UpdateStatus,
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
  getUpdateStatus: () => fetch('/api/updates', { cache: 'no-store', signal: AbortSignal.timeout(5000) }).then(r => json<UpdateStatus>(r)),
  checkUpdates: () => post<UpdateStatus>('/api/updates/check'),
  installUpdate: (version: string) => post<UpdateStatus>('/api/updates/install', { version }),
  pickPath: (mode: 'directory' | 'file', initial: string) =>
    post<NativePickerView>('/api/settings/pick', { mode, initial }),
  getSettings: () => fetch('/api/settings').then(r => json<SettingsView>(r)),
  saveSettings: (settings: SettingsUpdate) => fetch('/api/settings', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
  }).then(r => json<SettingsView>(r)),
  browse: (path: string, mode: 'directory' | 'file', signal?: AbortSignal) =>
    fetch(`/api/settings/browse?${new URLSearchParams({ ...(path ? { path } : {}), mode })}`, { signal })
      .then(r => json<BrowserView>(r)),
  getHealth: () =>
    fetch(`${BASE}/api/health`).then((r) => json<HealthResponse>(r)),

  listModels: () =>
    fetch(`${BASE}/api/models`).then((r) => json<ModelInfo[]>(r)),

  listLoras: () => fetch(`${BASE}/api/loras`).then((r) => json<LoraInfo[]>(r)),

  getFlagSchema: () =>
    fetch(`${BASE}/api/server/flags`).then((r) => json<FlagDef[]>(r)),

  getBinaryInfo: () =>
    fetch(`${BASE}/api/server/binary`).then((r) => json<BinaryInfo>(r)),

  getStatus: () =>
    fetch(`${BASE}/api/server/status`).then((r) => json<StatusResponse>(r)),

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

  listPresets: () =>
    fetch(`${BASE}/api/presets`).then((r) => json<Preset[]>(r)),

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
    fetch(`${BASE}/api/presets/${encodeURIComponent(name)}`, {
      method: "DELETE",
    }).then((r) => json<DeletedResponse>(r)),

  logsSocketUrl: () => {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${window.location.host}/api/server/logs`;
  },
};

export const instancesApi = {
  list: () => fetch("/api/instances").then((r) => json<InstanceView[]>(r)),
  create: (config: InstanceConfig) =>
    post<InstanceView>("/api/instances", config),
  update: (id: string, config: InstanceConfig) =>
    fetch(`/api/instances/${encodeURIComponent(id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    }).then((r) => json<InstanceView>(r)),
  remove: (id: string) =>
    fetch(`/api/instances/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }).then((r) => json<DeletedResponse>(r)),
};

export function instanceApi(id: string) {
  const scope = `?instance_id=${encodeURIComponent(id)}`;
  return {
    ...api,
    getFlagSchema: () =>
      api
        .getFlagSchema()
        .then((flags) => flags.filter((f) => f.key !== "port")),
    getStatus: () =>
      fetch(`/api/server/status${scope}`).then((r) => json<StatusResponse>(r)),
    startServer: (model_id: string, flags: FlagValues) =>
      post<StatusResponse>(`/api/server/start${scope}`, { model_id, flags }),
    stopServer: () => post<StatusResponse>(`/api/server/stop${scope}`),
    restartServer: (model_id: string, flags: FlagValues) =>
      post<RestartResponse>(`/api/server/restart${scope}`, { model_id, flags }),
    cancelRestart: () =>
      post<StatusResponse>(`/api/server/restart/cancel${scope}`),
    logsSocketUrl: () => api.logsSocketUrl() + scope,
  };
}
