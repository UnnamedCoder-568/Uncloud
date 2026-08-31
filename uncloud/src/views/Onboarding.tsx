import { useState } from 'react';
import { open } from '@tauri-apps/plugin-dialog';
import { setModelsDir, markOnboarded, getSettings } from '../lib/sidecar';
import Wordmark from '../components/Wordmark';

export default function Onboarding({ onDone }: { onDone: () => void }) {
  const [step, setStep] = useState<'welcome' | 'folder'>('welcome');
  const [folder, setFolder] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function pickFolder() {
    const existing = await getSettings().catch(() => null);
    const selected = await open({
      directory: true,
      multiple: false,
      defaultPath: existing?.models_dir,
      title: 'Choose a folder to store your models',
    });
    if (typeof selected === 'string') setFolder(selected);
  }

  async function finish() {
    if (!folder) return;
    setBusy(true);
    try {
      await setModelsDir(folder);
      await markOnboarded();
      onDone();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="h-full w-full flex flex-col items-center justify-center relative overflow-hidden">
      <div className="absolute inset-0 bg-[radial-gradient(#1a1a20_1px,transparent_1px)] [background-size:32px_32px] [mask-image:radial-gradient(ellipse_70%_50%_at_50%_40%,#000_60%,transparent_100%)]" />

      <div className="relative flex flex-col items-center gap-8 animate-in">
        <Wordmark size={42} />

        {step === 'welcome' && (
          <>
            <p className="text-[var(--text-dim)] text-sm max-w-sm text-center leading-relaxed">
              Run text, image, video, and voice models entirely on your own machine —
              online for the latest updates, or fully offline. Yours to control.
            </p>
            <button className="grad-button text-lg" onClick={() => setStep('folder')}>
              Get Started
            </button>
          </>
        )}

        {step === 'folder' && (
          <div className="flex flex-col items-center gap-5 w-[440px]">
            <p className="text-[var(--text-dim)] text-sm text-center">
              Choose where Uncloud should store and look for models. If you already have models
              downloaded, point Uncloud at that folder and it'll pick them up.
            </p>
            <button
              className="w-full card px-4 py-3 text-sm text-left hover:border-[#38383f] transition flex items-center justify-between"
              onClick={pickFolder}
            >
              <span className={folder ? 'text-[var(--text)]' : 'text-[var(--text-faint)]'}>
                {folder || 'No folder selected'}
              </span>
              <span className="text-[var(--text-dim)] text-xs font-mono">Browse</span>
            </button>
            <button className="grad-button text-base w-full" disabled={!folder || busy} onClick={finish}>
              {busy ? 'Setting up…' : 'Continue'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
