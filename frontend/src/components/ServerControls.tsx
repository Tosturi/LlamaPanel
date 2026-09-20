import type { StatusResponse } from "../types";

export function ServerControls({
  status,
  canStart,
  pending,
  onStart,
  onStop,
  onReload,
  onCancelRestart,
}: {
  status: StatusResponse | null;
  canStart: boolean;
  pending: "start" | "stop" | "reload" | null;
  onStart: () => void;
  onStop: () => void;
  onReload: () => void;
  onCancelRestart: () => void;
}) {
  const state = status?.state ?? "stopped";
  // `pending` covers the gap between clicking a button and the state poll/
  // response actually reflecting it (the backend may still be scanning the
  // models directory or spawning the process) - without it the buttons look
  // unresponsive for that stretch.
  const transitioning =
    state === "starting" ||
    state === "stopping" ||
    pending !== null ||
    status === null;
  const running = state === "running" || state === "starting";
  const restartQueued = status?.restart_pending ?? false;

  let badgeLabel: string = status ? state : "connecting";
  if (pending === "start" && state !== "starting") badgeLabel = "starting";
  else if (pending === "stop" && state !== "stopping") badgeLabel = "stopping";
  else if (restartQueued) badgeLabel = "reload queued";

  return (
    <div className="server-controls-block">
      <div className="server-controls">
        <span className={`state-badge state-${state}`}>
          {(transitioning || restartQueued) && <span className="spinner" />}
          {badgeLabel}
        </span>
        {running && (
          <span
            className={`badge inference-badge ${
              status?.busy === true
                ? "inference-active"
                : status?.busy === false
                  ? "inference-idle"
                  : "inference-unknown"
            }`}
          >
            <span className="dot" />
            {status?.busy === true
              ? "generating"
              : status?.busy === false
                ? "idle"
                : "inference: n/a"}
          </span>
        )}
        {status?.adopted && (
          <span
            className="badge"
            title="Detected running outside this panel session"
          >
            adopted
          </span>
        )}
        {status?.model_id && (
          <span className="muted">model: {status.model_id}</span>
        )}
        {status?.pid && <span className="muted">pid: {status.pid}</span>}
        <div className="spacer" />
        <button
          disabled={!canStart || running || transitioning}
          onClick={onStart}
        >
          Start
        </button>
        <button
          disabled={!canStart || !running || transitioning}
          onClick={onReload}
          title="Apply the current flags by restarting llama-server"
        >
          {pending === "reload" ? (
            <span className="spinner" />
          ) : (
            "Apply & restart"
          )}
        </button>
        <button disabled={!running || transitioning} onClick={onStop}>
          Stop
        </button>
      </div>

      {restartQueued && (
        <div className="restart-banner">
          <span className="spinner" />
          Идёт инференс — новые параметры будут применены (сервер
          перезапустится) сразу после его завершения.
          <button className="link-button" onClick={onCancelRestart}>
            Отменить
          </button>
        </div>
      )}
    </div>
  );
}
