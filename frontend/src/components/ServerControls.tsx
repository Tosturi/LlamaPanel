import type { StatusResponse } from "../types";

export function ServerControls({
  status,
  canStart,
  pending,
  onStart,
  onStop,
}: {
  status: StatusResponse | null;
  canStart: boolean;
  pending: "start" | "stop" | null;
  onStart: () => void;
  onStop: () => void;
}) {
  const state = status?.state ?? "stopped";
  // `pending` covers the gap between clicking a button and the state poll/
  // response actually reflecting it (the backend may still be scanning the
  // models directory or spawning the process) - without it the buttons look
  // unresponsive for that stretch.
  const busy = state === "starting" || state === "stopping" || pending !== null;
  const running = state === "running" || state === "starting";

  return (
    <div className="server-controls">
      <span className={`state-badge state-${state}`}>
        {busy && <span className="spinner" />}
        {pending === "start" && state !== "starting" ? "starting" : pending === "stop" && state !== "stopping" ? "stopping" : state}
      </span>
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
