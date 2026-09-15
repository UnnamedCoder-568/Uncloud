import { useEffect, useState } from 'react';
import { FolderPlus } from 'lucide-react';
import AddModel from './AddModel';
import { inDesktop } from '../lib/platform';

/**
 * "Add a model from disk…", wherever a model is chosen.
 *
 * It lived only on the Models page, so someone standing in front of an empty
 * picker with a model already downloaded had no idea the app could take it.
 * Desktop only: it reads folders on this computer, which a paired phone
 * cannot choose.
 *
 * The button only asks; `AddFromDiskHost`, mounted once, owns the dialog. The
 * buttons live inside dropdowns that close when clicked, and a dialog owned by
 * one would close with it.
 */

const OPEN = 'uncloud:add-model';

export default function AddFromDisk({
  label = 'Add a model from disk…',
  className = 'w-full flex items-center gap-2 text-left px-2.5 py-2 rounded-lg text-xs text-[var(--text-dim)] hover:text-white hover:bg-[var(--bg-inset)] transition',
  onOpen,
}: {
  label?: string;
  className?: string;
  /** Called as the dialog opens — a dropdown should close behind it. */
  onOpen?: () => void;
}) {
  if (!inDesktop()) return null;
  return (
    <button type="button" className={className}
            onClick={() => { window.dispatchEvent(new CustomEvent(OPEN)); onOpen?.(); }}>
      <FolderPlus size={13} className="shrink-0" />
      <span>{label}</span>
    </button>
  );
}

export function AddFromDiskHost() {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const show = () => setOpen(true);
    window.addEventListener(OPEN, show);
    return () => window.removeEventListener(OPEN, show);
  }, []);
  return open ? <AddModel onClose={() => setOpen(false)} onAdded={() => undefined} /> : null;
}
