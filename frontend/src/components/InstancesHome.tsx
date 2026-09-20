import { useState } from "react";
import { instancesApi } from "../api";
import type { InstanceView } from "../types";

export function InstancesHome({
  instances,
  onOpen,
  onRefresh,
}: {
  instances: InstanceView[];
  onOpen: (id: string) => void;
  onRefresh: () => void;
}) {
  const [name, setName] = useState("");
  const [port, setPort] = useState("8081");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [editing, setEditing] = useState<InstanceView | null>(null);
  const [showForm, setShowForm] = useState(false);
  const run = async (action: () => Promise<unknown>) => {
    setPending(true);
    setError("");
    try {
      await action();
      onRefresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setPending(false);
    }
  };
  return (
    <div className="app studio">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark">L/</span>LlamaPanel
        </div>
        <span className="muted">Local workspace</span>
      </header>
      <main>
        <div className="page-heading">
          <div>
            <p className="eyebrow">Your workspace</p>
            <h1>Servers</h1>
            <p className="muted">
              Independent models, ports and logs. Models and presets are shared.
            </p>
          </div>
          <button
            className="primary"
            onClick={() => {
              let next = 8080;
              while (instances.some((s) => s.port === next)) next++;
              setEditing(null);
              setName("");
              setPort(String(next));
              setShowForm(true);
            }}
          >
            Create server
          </button>
        </div>
        {error && (
          <div role="alert" className="error-banner">
            {error}
          </div>
        )}
        {showForm && (
          <form
            className="panel instance-form"
            onSubmit={(e) => {
              e.preventDefault();
              run(async () => {
                const config = {
                  name: name.trim(),
                  port: Number(port),
                  model_id: editing?.model_id ?? null,
                  flags: editing?.flags ?? {},
                };
                if (editing) await instancesApi.update(editing.id, config);
                else await instancesApi.create(config);
                setShowForm(false);
              });
            }}
          >
            <h2>{editing ? "Edit server" : "New server"}</h2>
            <label className="field-label">
              Name
              <input
                required
                maxLength={100}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label className="field-label">
              API port
              <input
                required
                type="number"
                min="1"
                max="65535"
                value={port}
                onChange={(e) => setPort(e.target.value)}
              />
            </label>
            <p className="muted">
              Each instance needs its own port. Stop the server before changing
              it.
            </p>
            <button disabled={pending || !name.trim()} type="submit">
              Save server
            </button>{" "}
            <button
              type="button"
              disabled={pending}
              onClick={() => setShowForm(false)}
            >
              Cancel
            </button>
          </form>
        )}
        <div className="library-grid">
          {instances.map((item) => (
            <article className="panel" key={item.id}>
              <div className="panel-header">
                <span className={`state-badge state-${item.status.state}`}>
                  {item.status.state}
                </span>
                <code>:{item.port}</code>
              </div>
              <h2>{item.name}</h2>
              <p className="muted">
                {item.status.model_id ?? item.model_id ?? "No model selected"}
              </p>
              <p className="muted">
                {item.status.pid &&
                ["running", "starting"].includes(item.status.state)
                  ? `PID ${item.status.pid}`
                  : "Ready to configure"}
                {item.status.restart_pending ? " · Restart queued" : ""}
              </p>
              <div className="instance-actions">
                <button className="primary" onClick={() => onOpen(item.id)}>
                  Open server →
                </button>
                <button
                  disabled={pending}
                  onClick={() => {
                    setEditing(item);
                    setName(item.name);
                    setPort(String(item.port));
                    setShowForm(true);
                  }}
                >
                  Edit
                </button>
                {item.id !== "default" && (
                  <button
                    className="danger-button"
                    disabled={
                      pending ||
                      ["running", "starting", "stopping"].includes(
                        item.status.state,
                      )
                    }
                    onClick={() => {
                      if (
                        window.confirm(
                          `Delete server “${item.name}”? Model files and presets will be kept.`,
                        )
                      )
                        run(() => instancesApi.remove(item.id));
                    }}
                  >
                    Delete
                  </button>
                )}
              </div>
            </article>
          ))}
        </div>
        {!instances.length && <p className="muted">Loading servers…</p>}
      </main>
    </div>
  );
}
