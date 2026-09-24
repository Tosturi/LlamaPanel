import { useEffect, useId, useRef, useState } from 'react';
import { api } from '../api';
import type { DownloadPlan, DownloadStatus } from '../types';

const size = (bytes: number) => `${(bytes / 1024 ** 3).toFixed(2)} GiB`;

export function ModelDownload({ onComplete }: { onComplete: () => void }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [source, setSource] = useState('');
  const [directory, setDirectory] = useState('');
  const [plan, setPlan] = useState<DownloadPlan | null>(null);
  const [choice, setChoice] = useState(0);
  const [status, setStatus] = useState<DownloadStatus | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const completed = useRef('');
  const onDone = useRef(onComplete);
  onDone.current = onComplete;
  const generation = useRef(0);
  const action = useRef(false);
  const busy = status?.phase === 'downloading';
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    api.getSettings().then(s => { if (!disposed) setDirectory(s.models_dir); }).catch(e => { if (!disposed) setError(String(e)); });
    const poll = async () => {
      const seen = generation.current;
      try {
        if (action.current) return;
        const next = await api.modelDownloadStatus();
        if (disposed || seen !== generation.current) return;
        setStatus(next);
        if (next.phase === 'downloading') setOpen(true);
        if (next.phase === 'complete' && completed.current !== next.id) {
          completed.current = next.id; onDone.current();
        }
      } catch (e) { if (!disposed) setError(String(e)); }
      finally { if (!disposed) timer = setTimeout(poll, 1500); }
    };
    poll();
    return () => { disposed = true; clearTimeout(timer); };
  }, []);
  const perform = async (fn: () => Promise<void>) => {
    action.current = true; generation.current++; setPending(true); setError('');
    try { await fn(); } catch (e) { setError(String(e)); }
    finally { action.current = false; generation.current++; setPending(false); }
  };
  return <section className="model-download">
    <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>Download from Hugging Face</button>
    {open && <div className="panel download-form">
      <form onSubmit={e => { e.preventDefault(); perform(async () => {
        setPlan(null); setChoice(0); setPlan(await api.resolveModelDownload(source));
      }); }}>
        <label className="field-label" htmlFor={`${id}-source`}>Repository / quantization</label>
        <div className="settings-path-row">
          <input id={`${id}-source`} required maxLength={256} value={source} disabled={pending || busy}
            placeholder="prism-ml/Ternary-Bonsai-2-27B-gguf:TQ1_0"
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
        <button className="primary" disabled={pending || !directory} onClick={() => perform(async () => {
          setStatus(await api.startModelDownload(plan.id, choice)); setPlan(null);
        })}>Download {size(plan.choices[choice].size)}</button>
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
