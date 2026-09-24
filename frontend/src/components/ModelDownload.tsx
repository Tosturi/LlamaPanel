import { useEffect, useId, useRef, useState } from 'react';
import { api } from '../api';
import type { DownloadPlan, DownloadStatus } from '../types';

const size = (bytes: number) => `${(bytes / 1024 ** 3).toFixed(2)} GiB`;

export function ModelDownload({ onComplete, active }: { onComplete: () => void; active: boolean }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [source, setSource] = useState('');
  const [directory, setDirectory] = useState('');
  const [plan, setPlan] = useState<DownloadPlan | null>(null);
  const [choice, setChoice] = useState(0);
  const [includeProjector, setIncludeProjector] = useState(false);
  const [projector, setProjector] = useState(0);
  const [wake, setWake] = useState(0);
  const [status, setStatus] = useState<DownloadStatus | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const completed = useRef('');
  const onDone = useRef(onComplete);
  onDone.current = onComplete;
  const generation = useRef(0);
  const action = useRef(false);
  const busy = status?.phase === 'downloading';
  const lastStatus = useRef(status);
  lastStatus.current = status;
  const selectedProjector = includeProjector ? plan?.projectors[projector] : null;
  const total = (plan?.choices[choice]?.size ?? 0) + (selectedProjector?.size ?? 0);
  useEffect(() => {
    if (!active) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    let inFlight = false;
    api.getSettings().then(s => { if (!disposed) setDirectory(s.models_dir); }).catch(e => { if (!disposed) setError(String(e)); });
    const poll = async () => {
      if (disposed || document.hidden || inFlight || action.current) return;
      inFlight = true;
      const seen = generation.current;
      let retry = false;
      try {
        const next = await api.modelDownloadStatus();
        if (disposed || seen !== generation.current) return;
        setStatus(next);
        if (next.phase === 'downloading') setOpen(true);
        retry = next.phase === 'downloading';
        if (next.phase === 'complete' && completed.current !== next.id) {
          completed.current = next.id; onDone.current();
        }
      } catch (e) {
        if (!disposed) setError(String(e));
        retry = lastStatus.current?.phase === 'downloading';
      }
      finally {
        inFlight = false;
        if (!disposed && !document.hidden && retry) timer = setTimeout(poll, 5000);
      }
    };
    const visibility = () => { clearTimeout(timer); if (!document.hidden) poll(); };
    document.addEventListener('visibilitychange', visibility);
    poll();
    return () => { disposed = true; clearTimeout(timer); document.removeEventListener('visibilitychange', visibility); };
  }, [active, open, wake]);
  const perform = async (fn: () => Promise<void>) => {
    action.current = true; generation.current++; setPending(true); setError('');
    try { await fn(); } catch (e) { setError(String(e)); }
    finally { action.current = false; generation.current++; setPending(false); setWake(w => w + 1); }
  };
  return <section className="model-download">
    <button type="button" aria-expanded={open || busy} onClick={() => setOpen(!open)}>Download from Hugging Face</button>
    {(open || busy) && <div className="panel download-form">
      <form onSubmit={e => { e.preventDefault(); perform(async () => {
        setPlan(null); setChoice(0); setIncludeProjector(false); setProjector(0); setPlan(await api.resolveModelDownload(source));
      }); }}>
        <div className="settings-path-row">
          <input id={`${id}-source`} required maxLength={256} value={source} disabled={pending || busy}
            aria-label="Hugging Face repository"
            placeholder="author/repository (e.g., unsloth/Qwen3.8-27B-GGUF)"
            onChange={e => { setSource(e.target.value); setPlan(null); }} />
          <button disabled={pending || busy || !source.trim()}>{pending ? 'Please wait…' : 'Review files'}</button>
        </div>
      </form>
      <p className="muted">Save to <code className="file-path">{busy ? status.directory : directory}</code></p>
      {plan && !busy && <>
        <label className="field-label" htmlFor={`${id}-choice`}>Model files</label>
        <select id={`${id}-choice`} value={choice} disabled={pending} onChange={e => setChoice(Number(e.target.value))}>
          {plan.choices.map((c, i) => <option key={c.name} value={i}>{c.name} · {size(c.size)}</option>)}
        </select>
        <ul className="download-files">{plan.choices[choice].files.map(f => <li key={f.path}>{f.path} · {size(f.size)}</li>)}</ul>
        <span className="projector-option" tabIndex={plan.projectors.length ? undefined : 0}
          aria-describedby={plan.projectors.length ? undefined : `${id}-projector-tip`}>
          <label><input type="checkbox" checked={includeProjector} disabled={pending || !plan.projectors.length}
            onChange={e => setIncludeProjector(e.target.checked)} /> Download mmproj</label>
          {!plan.projectors.length && <span className="projector-tip" id={`${id}-projector-tip`} role="tooltip">No separate multimodal projector was found in this repository.</span>}
        </span>
        {includeProjector && <>
          {plan.projectors.length > 1 && <select aria-label="Multimodal projector" value={projector} disabled={pending} onChange={e => setProjector(Number(e.target.value))}>
            {plan.projectors.map((p, i) => <option key={p.name} value={i}>{p.name} · {size(p.size)}</option>)}
          </select>}
          <ul className="download-files">{selectedProjector?.files.map(f => <li key={f.path}>{f.path} · {size(f.size)}</li>)}</ul>
        </>}
        <button className="primary" disabled={pending || !directory} onClick={() => perform(async () => {
          setStatus(await api.startModelDownload(plan.id, choice, includeProjector ? projector : null)); setPlan(null);
        })}>Download {size(total)}</button>
      </>}
      {busy && <>
        <p className="file-path">{status.name}</p>
        <progress aria-label="Model download" value={status.downloaded} max={status.total || 1} />
        <p role="status">{size(status.downloaded)} / {size(status.total)} · {status.total ? Math.floor(100 * status.downloaded / status.total) : 0}%</p>
        <button disabled={pending} onClick={() => perform(async () => { setStatus(await api.cancelModelDownload()); })}>Cancel download</button>
      </>}
      {status && status.phase !== 'idle' && <p role={status.phase === 'failed' ? 'alert' : 'status'} className={status.phase === 'failed' ? 'error-banner' : 'muted'}>{status.message}</p>}
      {error && <p role="alert" className="error-banner">{error}</p>}
    </div>}
  </section>;
}
