import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { UpdatePanel } from './UpdatePanel';
import type { BrowserView, SettingsUpdate, SettingsView } from '../types';

const fields = [
  ['models_dir', 'Models directory'],
  ['loras_dir', 'LoRA directory'],
] as const;

function PathBrowser({ mode, onSelect, onClose }: {
  mode: 'directory' | 'file'; onSelect: (path: string) => void; onClose: () => void;
}) {
  const [listing, setListing] = useState<BrowserView | null>(null);
  const [path, setPath] = useState('');
  const [filter, setFilter] = useState('');
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const request = useRef<AbortController | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const navigate = async (target: string) => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setBusy(true); setError(''); setListing(null); setFilter('');
    try {
      const result = await api.browse(target, mode, controller.signal);
      if (!controller.signal.aborted) { setListing(result); setPath(result.path); }
    } catch (e) {
      if (!controller.signal.aborted) setError(String(e));
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  };
  useEffect(() => {
    dialog.current?.showModal();
    navigate(''); input.current?.focus();
    return () => request.current?.abort();
  }, []);
  return <dialog ref={dialog} className="panel path-browser" aria-label="Browse backend files" onCancel={e => { e.preventDefault(); onClose(); }}>
    <div className="panel-header"><h2>{mode === 'directory' ? 'Select folder' : 'Select executable'}</h2>
      <button type="button" onClick={onClose}>Close browser</button></div>
    <p className="muted">Files on the machine running LlamaPanel.</p>
    <div className="settings-path-row">
      <input ref={input} aria-label="Directory path" value={path} disabled={busy} onChange={e => setPath(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); navigate(path); } }} />
      <button type="button" disabled={busy} onClick={() => navigate(path)}>Go</button>
    </div>
    {error && <p role="alert" className="error-banner">{error}</p>}
    {busy && <p role="status">Loading folders…</p>}
    {listing && <>
      <div className="instance-actions browser-roots">
        <button type="button" disabled={!listing.parent} onClick={() => navigate(listing.parent!)}>Up</button>
        <button type="button" onClick={() => navigate('')}>Home</button>
        {listing.roots.map(root => <button type="button" key={root} onClick={() => navigate(root)}>{root}</button>)}
      </div>
      <input aria-label="Filter files and folders" placeholder="Filter files and folders" value={filter} onChange={e => setFilter(e.target.value)} />
      <div className="browser-entries">
        {listing.entries.filter(e => e.name.toLowerCase().includes(filter.toLowerCase())).map(entry =>
          <button type="button" key={entry.path} onClick={() => entry.directory ? navigate(entry.path) : onSelect(entry.path)}>
            <span aria-hidden="true">{entry.directory ? '▸' : '◇'}</span> {entry.name}{entry.directory ? '/' : ''}
          </button>)}
        {!listing.entries.length && <p className="muted">No {mode === 'directory' ? 'subfolders' : 'files'} here.</p>}
      </div>
      {mode === 'directory' && <button type="button" className="primary" disabled={path !== listing.path} onClick={() => onSelect(listing.path)}>Select this folder</button>}
    </>}
  </dialog>;
}

type PathKey = 'models_dir' | 'loras_dir' | 'server_bin' | `runtime:${string}`;

export function SettingsPage({ onBack, onSaved }: { onBack: () => void; onSaved: (value: SettingsView) => void }) {
  const [settings, setSettings] = useState<SettingsView | null>(null);
  const [values, setValues] = useState<SettingsUpdate | null>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [pending, setPending] = useState(false);
  const [updateBusy, setUpdateBusy] = useState(false);
  const [picking, setPicking] = useState(false);
  const pickingRef = useRef(false);
  const [browser, setBrowser] = useState<PathKey | null>(null);
  const browseButton = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    let active = true;
    api.getSettings().then(s => { if (active) { setSettings(s); setValues({models_dir:s.models_dir,loras_dir:s.loras_dir,server_bin:s.server_bin,runtimes:s.runtimes}); } })
      .catch(e => { if (active) setError(String(e)); });
    return () => { active = false; };
  }, []);
  const closeBrowser = () => { setBrowser(null); browseButton.current?.focus(); };
  const setPath = (key: PathKey, path: string) => {
    setValues(prev => {
      if (!prev) return prev;
      if (key.startsWith('runtime:')) return {...prev, runtimes:(prev.runtimes ?? []).map(r => r.id === key.slice(8) ? {...r, server_bin:path} : r)};
      return {...prev, [key]:path};
    });
    setMessage('');
  };
  const pathValue = (key: PathKey) => key.startsWith('runtime:')
    ? values?.runtimes?.find(r => r.id === key.slice(8))?.server_bin ?? ''
    : String(values?.[key as 'models_dir' | 'loras_dir' | 'server_bin'] ?? '');
  const fileMode = (key: PathKey) => key === 'server_bin' || key.startsWith('runtime:');
  const browse = async (key: PathKey) => {
    if (!values || pickingRef.current) return;
    pickingRef.current = true;
    setPicking(true); setError(''); setMessage('');
    try {
      const result = await api.pickPath(fileMode(key) ? 'file' : 'directory', pathValue(key));
      if (!result.available) setBrowser(key);
      else if (result.path) setPath(key, result.path);
    } catch (e) { setError(String(e)); }
    finally { pickingRef.current = false; setPicking(false); browseButton.current?.focus(); }
  };
  return <div className="app studio">
    <header className="app-header"><div className="brand"><span className="brand-mark">L/</span>LlamaPanel</div></header>
    <main>
      <div className="page-heading settings-heading">
        <button onClick={onBack} disabled={pending || picking || updateBusy}>← Back</button>
        <h1>Settings</h1>
      </div>
      {error && <p className="error-banner" role="alert">{error}</p>}
      {!values && !error && <p role="status">Loading settings…</p>}
      {values && settings && <form className="settings-form" onSubmit={async e => {
        e.preventDefault(); setPending(true); setError(''); setMessage('');
        try {
          const saved = await api.saveSettings(values);
          setSettings(saved); setValues({models_dir:saved.models_dir,loras_dir:saved.loras_dir,server_bin:saved.server_bin,runtimes:saved.runtimes});
          onSaved(saved); setMessage('Settings saved. Libraries updated. Running servers are unchanged.');
        } catch (e) { setError(String(e)); }
        finally { setPending(false); }
      }}>
        <section className="panel settings-form">
        <h2>Libraries</h2>
        {fields.map(([key, label]) => <div key={key}>
          <label className="field-label" htmlFor={`settings-${key}`}>{label}</label>
          <div className="settings-path-row">
            <input id={`settings-${key}`} required value={values[key]} disabled={pending || picking || updateBusy || settings.locked_fields.includes(key)}
              onChange={e => { setValues({...values, [key]:e.target.value}); setMessage(''); }} />
            <button type="button" disabled={pending || picking || updateBusy || settings.locked_fields.includes(key)} aria-label={`Browse ${label}`}
              onClick={e => { browseButton.current = e.currentTarget; browse(key); }}>Browse…</button>
          </div>
          {settings.locked_fields.includes(key) && <p className="muted">Set by a launch argument or environment variable.</p>}
        </div>)}
        </section>
        <section className="panel settings-form">
          <h2>llama-server runtimes</h2>
          <div>
            <label className="field-label" htmlFor="settings-server_bin">Default llama-server</label>
            <div className="settings-path-row">
              <input id="settings-server_bin" required value={values.server_bin}
                disabled={pending || picking || updateBusy || settings.locked_fields.includes('server_bin')}
                onChange={e => setPath('server_bin', e.target.value)} />
              <button type="button" disabled={pending || picking || updateBusy || settings.locked_fields.includes('server_bin')}
                onClick={e => {browseButton.current = e.currentTarget; browse('server_bin');}}>Browse…</button>
            </div>
            {settings.locked_fields.includes('server_bin') && <p className="muted">Set by a launch argument or environment variable.</p>}
          </div>
          {(values.runtimes ?? []).map(runtime => <div className="runtime-entry" key={runtime.id}>
            <div className="settings-path-row">
              <input aria-label="Runtime name" required maxLength={100} placeholder="Runtime name" value={runtime.name}
                disabled={pending || picking || updateBusy}
                onChange={e => { setValues({...values, runtimes:values.runtimes!.map(r => r.id === runtime.id ? {...r, name:e.target.value} : r)}); setMessage(''); }} />
              <button type="button" aria-label={`Remove ${runtime.name || 'runtime'}`} disabled={pending || picking || updateBusy}
                onClick={() => {setValues({...values, runtimes:values.runtimes!.filter(r => r.id !== runtime.id)}); setMessage('');}}>Remove</button>
            </div>
            <div className="settings-path-row">
              <input aria-label={`Executable for ${runtime.name || 'runtime'}`} required value={runtime.server_bin} placeholder="llama-server executable"
                disabled={pending || picking || updateBusy} onChange={e => setPath(`runtime:${runtime.id}`, e.target.value)} />
              <button type="button" disabled={pending || picking || updateBusy}
                onClick={e => {browseButton.current = e.currentTarget; browse(`runtime:${runtime.id}`);}}>Browse…</button>
            </div>
          </div>)}
          <button className="add-runtime" type="button" disabled={pending || picking || updateBusy}
            onClick={() => {setValues({...values, runtimes:[...(values.runtimes ?? []), {id:`runtime-${Date.now()}-${Math.random().toString(36).slice(2,8)}`, name:'', server_bin:''}]}); setMessage('');}}>+ Add runtime</button>
        </section>
        <p className="muted">Choose paths on the backend machine. The executable is used for future starts and restarts. Already queued restarts keep their original configuration.</p>
        <p className="muted">Settings, presets and logs: <code className="file-path">{settings.data_dir}</code></p>
        <button className="primary" disabled={pending || picking || updateBusy || browser !== null}>{pending ? 'Saving…' : 'Save settings'}</button>
        {picking && <p role="status">Choose a path in the system dialog…</p>}
        <p role="status">{message}</p>
      </form>}
      <UpdatePanel onBusy={setUpdateBusy} disabled={pending || picking || browser !== null || !values || !settings || fields.some(([key]) => values[key] !== settings[key]) || values?.server_bin !== settings?.server_bin || JSON.stringify(values?.runtimes) !== JSON.stringify(settings?.runtimes)} />
      {browser && values && <PathBrowser key={browser} mode={fileMode(browser) ? 'file' : 'directory'}
        onClose={closeBrowser} onSelect={path => { setPath(browser,path); closeBrowser(); }} />}
    </main>
  </div>;
}
