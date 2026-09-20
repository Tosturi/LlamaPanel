import { useEffect, useRef, useState } from "react";
import { api } from "../api";

// How close to the bottom (px) the user has to be for new lines to keep the
// view pinned to the end. Scrolling further up pauses auto-scroll so older
// output can be read without being yanked back down on every new line.
const STICK_THRESHOLD_PX = 24;

export function LogViewer({
  socketUrl = api.logsSocketUrl(),
}: {
  socketUrl?: string;
}) {
  const [lines, setLines] = useState<string[]>([]);
  const containerRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  useEffect(() => {
    const ws = new WebSocket(socketUrl);
    ws.onmessage = (ev) =>
      setLines((prev) => [...prev.slice(-999), ev.data as string]);
    return () => ws.close();
  }, [socketUrl]);

  useEffect(() => {
    // Scroll the log container itself, never scrollIntoView(): that walks
    // every scrollable ancestor - including the page - and made the whole
    // layout jump each time a line arrived.
    const el = containerRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [lines]);

  const onScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    stickToBottom.current =
      el.scrollHeight - el.scrollTop - el.clientHeight <= STICK_THRESHOLD_PX;
  };

  return (
    <div className="log-viewer" ref={containerRef} onScroll={onScroll}>
      {lines.map((line, i) => (
        <div key={i} className="log-line">
          {line}
        </div>
      ))}
    </div>
  );
}
