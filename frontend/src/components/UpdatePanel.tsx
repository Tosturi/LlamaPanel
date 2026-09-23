import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { UpdateStatus } from '../types';

const progress = ['downloading', 'preparing', 'restarting'];
const marker = 'llamapanel-update-pending';
const remembered = () => { try { return sessionStorage.getItem(marker) !== null; } catch { return false; } };
const remember = (active: boolean) => { try { if (active) sessionStorage.setItem(marker, '1'); else sessionStorage.removeItem(marker); } catch { /* storage may be unavailable */ } };

export function UpdatePanel({ disabled, onBusy }: { disabled: boolean; onBusy: (busy: boolean) => void }) {
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [error, setError] = useState('');
  const [checking, setChecking] = useState(false);
  const [installing, setInstalling] = useState(remembered);
  const reconnecting = useRef(remembered());
  const generation = useRef(0);
  const actionPending = useRef(false);
  const busy = installing || !!status && progress.includes(status.phase);
  useEffect(() => { onBusy(busy); }, [busy, onBusy]);
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      const seen = generation.current;
      try {
        if (actionPending.current) return;
        const next = await api.getUpdateStatus();
        if (disposed || seen !== generation.current) return;
        setStatus(next); setError('');
        if (reconnecting.current && next.phase === 'complete') {
          remember(false);
          window.location.reload();
          return;
        }
        if (reconnecting.current && (next.phase === 'failed' || next.phase === 'idle' || !next.supported)) {
          reconnecting.current = false; remember(false); setInstalling(false);
        }
      } catch (e) {
        if (!disposed) setError(reconnecting.current ? 'Reconnecting to the panel…' : String(e));
      } finally {
        if (!disposed) timer = setTimeout(poll, 2000);
      }
    };
    poll();
    return () => { disposed = true; clearTimeout(timer); };
  }, []);
  return <section className="panel updates-panel" aria-labelledby="updates-title">
    <div className="panel-header"><h2 id="updates-title">Updates</h2>
      {status && <span className="badge">v{status.current_version}</span>}</div>
    {status?.reason && <p className="muted">{status.reason}</p>}
    {status?.latest_version && <p>{status.available ? `Version ${status.latest_version} is available.` : 'You are up to date.'}</p>}
    <div className="instance-actions">
      <button disabled={busy || checking} onClick={async () => {
        generation.current++; actionPending.current = true; setChecking(true); setError('');
        try { setStatus(await api.checkUpdates()); }
        catch (e) { setError(String(e)); }
        finally { generation.current++; actionPending.current = false; setChecking(false); }
      }}>{checking ? 'Checking…' : 'Check for updates'}</button>
      {status?.available && <button className="primary"
        disabled={disabled || busy || checking || !status.supported}
        onClick={async () => {
          if (!status.latest_version) return;
          generation.current++; actionPending.current = true; setInstalling(true); setError('');
          reconnecting.current = true; remember(true);
          try { setStatus(await api.installUpdate(status.latest_version)); }
          catch (e) {
            // A lost connection can mean the panel is already restarting.
            try {
              const current = await api.getUpdateStatus();
              setStatus(current);
              if (!progress.includes(current.phase) && current.phase !== 'complete') {
                reconnecting.current = false; remember(false); setInstalling(false); setError(String(e));
              }
            } catch { setError('Reconnecting to the panel…'); }
          }
          finally { generation.current++; actionPending.current = false; }
        }}>Update & restart</button>}
    </div>
    {status?.supported && <p className="muted">Save configuration changes before updating. The panel restarts; running llama-server instances stay active.</p>}
    {disabled && status?.available && <p className="muted">Save your settings and close the file picker before updating.</p>}
    {(busy || status?.message) && <p role="status">{busy && <span className="spinner" />} {status?.message || 'Starting update…'}</p>}
    {error && <p role={busy ? 'status' : 'alert'} className={busy ? 'muted' : 'error-banner'}>{error}</p>}
    {status?.notes && <details><summary>Release notes</summary><pre className="release-notes">{status.notes}</pre></details>}
  </section>;
}
