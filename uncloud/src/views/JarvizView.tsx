import CapabilityGate from '../components/CapabilityGate';
import { useState } from 'react';
import Panes from '../components/Panes';
import VoiceTools from './VoiceTools';
import NarrationView from './NarrationView';
import SpeechStudio from './SpeechStudio';
import { Talk, Convert } from './VoiceToVoice';
import ClipsView from './ClipsView';

type Tab = 'talk' | 'text' | 'convert' | 'transcribe' | 'clips';

const TABS: { id: Tab; label: string; hint: string }[] = [
  { id: 'talk', label: 'Talk', hint: 'Speak to your selected model' },
  { id: 'text', label: 'Text to voice', hint: 'Type something and hear it spoken' },
  { id: 'convert', label: 'Convert voice', hint: 'Re-voice a recording' },
  { id: 'transcribe', label: 'Transcribe', hint: 'Speech to text' },
  { id: 'clips', label: 'Clips', hint: 'Everything spoken, kept' },
];

/** The engines Text to voice offers. VibeVoice keeps its own long-form panel,
 *  which reads a whole script in one pass. */
const ENGINES: { id: string; label: string; hint: string }[] = [
  { id: 'kokoro', label: 'Kokoro', hint: 'Quick, natural preset voices' },
  { id: 'kokoro-mlx', label: 'Kokoro · Apple Silicon', hint: 'Apple GPU speech; faster after warmup' },
  { id: 'chatterbox', label: 'Chatterbox', hint: 'Expressive; speaks in a recorded voice' },
  { id: 'bark', label: 'Bark', hint: 'Characterful, slow' },
  { id: 'vibevoice', label: 'VibeVoice', hint: 'Long-form narration in one pass' },
];

export default function JarvizView() {
  const [tab, setTab] = useState<Tab>('talk');
  const [engine, setEngine] = useState(() => {
    try { return localStorage.getItem('uncloud.voice.engine') || 'kokoro'; } catch { return 'kokoro'; }
  });

  function chooseEngine(id: string) {
    setEngine(id);
    try { localStorage.setItem('uncloud.voice.engine', id); } catch { /* storage refused */ }
  }

  return (
    <div className="h-full flex flex-col">
      <header className="px-6 pt-5 pb-3">
        <h1 className="page-title">Jarviz</h1>
        <p className="text-sm text-[var(--text-dim)] mt-2">Voice conversation, speech creation and recordings.</p>
      </header>
      <div className="view-tabs" role="tablist" aria-label="Jarviz">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            title={t.hint}
            className={`text-xs px-3 py-1.5 rounded-lg transition whitespace-nowrap ${
              tab === t.id
                ? 'bg-[var(--bg-raised)] text-[var(--text)]'
                : 'text-[var(--text-faint)] hover:text-[var(--text-dim)] hover:bg-[var(--bg-raised)]/50'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === 'text' && (
        <div className="shrink-0 border-b border-[var(--border-soft)] px-4 py-2 flex gap-1 overflow-x-auto">
          {ENGINES.map((e) => (
            <button key={e.id} onClick={() => chooseEngine(e.id)} title={e.hint}
                    className={engine === e.id ? 'pill pill-on' : 'pill'}>
              <span>{e.label}</span>
            </button>
          ))}
        </div>
      )}
      <div className="flex-1 min-h-0">
        <Panes
          active={tab === 'text' ? (engine === 'vibevoice' ? 'narrate' : 'speech') : tab}
          className="h-full"
          panes={[
            { id: 'speech', render: () => <CapabilityGate names={engine === 'vibevoice' ? 'kokoro' : engine}><SpeechStudio engineId={engine === 'vibevoice' ? 'kokoro' : engine} /></CapabilityGate> },
            { id: 'narrate', render: () => <CapabilityGate names="realtime,quality"><NarrationView /></CapabilityGate> },
            { id: 'talk', render: () => <CapabilityGate names="chat,transcribe,kokoro"><Talk /></CapabilityGate> },
            { id: 'convert', render: () => <CapabilityGate names="chatterbox"><Convert /></CapabilityGate> },
            { id: 'transcribe', render: () => <CapabilityGate names="transcribe"><VoiceTools /></CapabilityGate> },
            { id: 'clips', render: () => <ClipsView /> },
          ]}
        />
      </div>
    </div>
  );
}
