import { useEffect, useRef, useState } from "react";
import { api } from "../api";

export function LogViewer() {
  const [lines, setLines] = useState<string[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const ws = new WebSocket(api.logsSocketUrl());
    ws.onmessage = (ev) => setLines((prev) => [...prev.slice(-999), ev.data as string]);
    return () => ws.close();
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [lines]);

  return (
    <div className="log-viewer">
      {lines.map((line, i) => (
        <div key={i} className="log-line">
          {line}
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
