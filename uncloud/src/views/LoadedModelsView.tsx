import { useCallback, useEffect, useState } from 'react';
import ResidentModelList from '../components/ResidentModelList';
import { useWhenVisible } from '../components/Panes';
import { getResident, type ResidentModels } from '../lib/sidecar';

export default function LoadedModelsView() {
  const [resident, setResident] = useState<ResidentModels | null>(null);
  const [error, setError] = useState('');
  const refresh = useCallback(() => {
    void getResident().then(value => { setResident(value); setError(''); }).catch(e => setError(String(e)));
  }, []);
  useEffect(refresh, [refresh]);
  useWhenVisible(refresh);
  return <div className="h-full overflow-y-auto"><div className="page-column flex flex-col gap-5">
    <header className="flex items-start justify-between gap-4"><div>
      <h2 className="page-title">Loaded models</h2>
      <p className="text-sm text-[var(--text-dim)] mt-2">Everything currently held by Uncloud’s engines.</p>
    </div><button className="pill" onClick={refresh}>Refresh</button></header>
    {error && <p role="alert" className="text-xs">{error}</p>}
    <section className="card p-5">
      {resident?.anything ? <ResidentModelList resident={resident} /> : <p className="text-sm text-[var(--text-dim)]">{resident ? 'No models loaded. Choose a model in Chat or Chisel to begin.' : 'Checking loaded models…'}</p>}
    </section>
    <p className="text-xs text-[var(--text-dim)]">Switching the text model unloads the previous one first. Image and voice engines appear here while they are loaded.</p>
  </div></div>;
}
