import { useSyncExternalStore } from 'react';

const key = 'uncloud.image.auto-enhance';
const change = 'uncloud-auto-enhance-changed';
function read() {
  try { return localStorage.getItem(key) !== 'false'; } catch { return true; }
}
function subscribe(listener: () => void) {
  window.addEventListener(change, listener);
  window.addEventListener('storage', listener);
  return () => {
    window.removeEventListener(change, listener);
    window.removeEventListener('storage', listener);
  };
}

export function useAutoImageEnhancement(): [boolean, (value: boolean) => void] {
  const enabled = useSyncExternalStore(subscribe, read, () => true);
  return [enabled, value => {
    try { localStorage.setItem(key, String(value)); } catch { /* private storage */ }
    window.dispatchEvent(new Event(change));
  }];
}

export default function AutoImageEnhancement({ disabled = false }: { disabled?: boolean }) {
  const [enabled, setEnabled] = useAutoImageEnhancement();
  return <div className="flex flex-col gap-1.5">
    <label className="flex items-center gap-2 text-xs text-[var(--text-dim)]">
      <input type="checkbox" checked={enabled} disabled={disabled}
        onChange={event => setEnabled(event.target.checked)} />
      Automatic 2× enhancement
    </label>
    <p className="text-[10px] text-[var(--text-faint)] leading-snug">
      Runs after rendering and keeps the original. First use downloads 64 MB.
    </p>
  </div>;
}
