import { useState } from 'react';
import VoiceTools from './VoiceTools';
import NarrationView from './NarrationView';

type Tab = 'narrate' | 'tools';

const TABS: { id: Tab; label: string; hint: string }[] = [
  { id: 'narrate', label: 'Narration', hint: 'Long-form, one pass, consistent voice' },
  { id: 'tools', label: 'Transcribe & Speak', hint: 'Short clips and speech-to-text' },
];

export default function VoiceView() {
  const [tab, setTab] = useState<Tab>('narrate');

  return (
    <div className="h-full flex flex-col">
      <div className="h-12 shrink-0 border-b border-[var(--border-soft)] flex items-center px-4 gap-1">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            title={t.hint}
            className={`text-xs px-3 py-1.5 rounded-lg transition ${
              tab === t.id
                ? 'bg-[var(--bg-raised)] text-white'
                : 'text-[var(--text-faint)] hover:text-[var(--text-dim)] hover:bg-[var(--bg-raised)]/50'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="flex-1 min-h-0">
        {tab === 'narrate' && <NarrationView />}
        {tab === 'tools' && <VoiceTools />}
      </div>
    </div>
  );
}
