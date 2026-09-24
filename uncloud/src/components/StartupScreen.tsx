import type { ReactNode } from 'react';
import ActivityOrb from './ActivityOrb';
import Wordmark from './Wordmark';

export default function StartupScreen({ status, children }: { status: string; children?: ReactNode }) {
  return <div className="h-screen w-screen overflow-auto dot-ground flex flex-col p-8 text-center">
    <div className="glow flex flex-col items-center gap-4 w-full max-w-xl mx-auto my-auto py-8">
      <ActivityOrb state="connecting" size={64} label={status} />
      <Wordmark size={32} />
      <p role="status" className="text-sm text-[var(--text-dim)]">{status}</p>
      {children}
    </div>
  </div>;
}
