import type { StatusResponse } from "../types";

export function ServerControls({
  status,
  canStart,
  onStart,
  onStop,
}: {
  status: StatusResponse | null;
  canStart: boolean;
  onStart: () => void;
  onStop: () => void;
}) {
  const state = status?.state ?? "stopped";
  const busy = state === "starting" || state === "stopping";
  const running = state === "running" || state === "starting";

  return (
    <div className="server-controls">
      <span className={`state-badge state-${state}`}>{state}</span>
      {status?.adopted && <span className="badge" title="Detected running outside this panel session">adopted</span>}
      {status?.model_id && <span className="muted">model: {status.model_id}</span>}
      {status?.pid && <span className="muted">pid: {status.pid}</span>}
      <div className="spacer" />
      <button disabled={!canStart || running || busy} onClick={onStart}>
        Start
      </button>
      <button disabled={!running || busy} onClick={onStop}>
        Stop
      </button>
    </div>
  );
}
