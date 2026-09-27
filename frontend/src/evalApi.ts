import type { components } from "./api-types";
export type Participant = components["schemas"]["EvalParticipant"];
export type ComparisonRequest = components["schemas"]["EvalRequest"];
export type Benchmark = {
  id: string;
  name: string;
  description?: string;
  scorer?: string;
  samples: number;
  bytes?: number;
  source?: string;
  recipe?: string;
  catalog_id?: string;
  error?: string;
};
export type Library = {
  directory: string;
  installed: Benchmark[];
  catalog: {
    id: string;
    name: string;
    description: string;
    download_bytes: number;
    license: string;
    source: string;
  }[];
  download: { state: string; bytes: number; error?: string };
};
export type Metric = {
  participant: number;
  benchmark: string;
  name: string;
  total: number;
  scored: number;
  errors: number;
  score: number | null;
  metric: string;
  harness_metric?: string;
  stderr?: number | null;
};
export type Run = {
  id: string;
  name: string;
  state: string;
  created_at: number;
  completed: number;
  total: number;
  error?: string | null;
  current?: string;
  phase?: string;
  requests_completed?: number;
  requests_total?: number;
  judge_completed?: number;
  judge_total?: number;
  participants: (Participant & {
    effective_concurrency: number;
    calibration: {
      concurrency: number;
      tokens_per_second?: number;
      error?: string;
    }[];
  })[];
  metrics: Record<string, Metric>;
  request: ComparisonRequest;
};
export type Sample = {
  participant: number;
  benchmark: string;
  sample_id: string;
  phase: string;
  status: string;
  output?: string;
  score?: number | null;
  error?: string;
  expected?: string;
  judge_output?: string;
  harness_metrics?: Record<string, unknown>;
  messages?: { role: string; content: string }[];
};
export class EvalError extends Error {
  constructor(public detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
}
export async function evalApi<T>(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`/api/evaluations${path}`, {
    method,
    signal,
    headers:
      body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new EvalError(data.detail ?? data);
  return data;
}
export const activeStates = new Set([
  "preparing",
  "loading",
  "running",
  "judging",
  "calibrating",
  "pausing",
  "paused",
  "cancelling",
]);
