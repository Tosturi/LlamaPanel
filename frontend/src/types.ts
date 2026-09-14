export interface ModelPart {
  filename: string;
  path: string;
  size_bytes: number;
}

export interface ModelInfo {
  id: string;
  display_name: string;
  entry_path: string;
  parts: ModelPart[];
  total_size_bytes: number;
  architecture: string | null;
  file_type: string | null;
  context_length: number | null;
  is_split: boolean;
}

export type FlagType = "boolean" | "number" | "string" | "enum" | "path";

export interface FlagDef {
  key: string;
  cli: string;
  type: FlagType;
  label: string;
  group: "basic" | "advanced";
  default: boolean | number | string | null;
  options: string[] | null;
  help: string | null;
}

export type ServerState = "stopped" | "starting" | "running" | "stopping" | "crashed";

export interface StatusResponse {
  state: ServerState;
  pid: number | null;
  model_id: string | null;
  args: string[] | null;
  flags: FlagValues | null;
  adopted: boolean;
  started_at: number | null;
  exit_code: number | null;
  busy: boolean | null; // null = unknown (server unreachable, or started with --no-slots)
  restart_pending: boolean;
}

export interface RestartResponse {
  result: "applied" | "queued";
  status: StatusResponse;
}

export type FlagValues = Record<string, boolean | number | string | null>;

export interface Preset {
  name: string;
  model_id: string;
  flags: FlagValues;
}
