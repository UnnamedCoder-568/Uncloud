import CapabilityGate from '../components/CapabilityGate';
/**
 * Models: what is installed, and the two things you do to a model.
 *
 * Training and quantising were a sidebar entry and a card buried in the middle
 * of this page respectively, which is two different answers to the same
 * question — where does work ON a model live? They are tabs here for the
 * reason Image has tabs: one subject, several operations on it, and the rail
 * stays a list of subjects rather than a list of everything.
 *
 * Order is the order they happen in. You install a model, you make a version
 * that fits the machine, and only then is fine-tuning it worth the afternoon.
 */

import { useState } from 'react';
import Panes from '../components/Panes';
import ModelsLibrary from './ModelsLibrary';
import TrainingView from './TrainingView';
import QuantizeView from './QuantizeView';

type Tab = 'library' | 'quantize' | 'train';

const TABS: { id: Tab; label: string }[] = [
  { id: 'library', label: 'Library' },
  { id: 'quantize', label: 'Quantize' },
  { id: 'train', label: 'Train' },
];

export default function ModelsView() {
  const [tab, setTab] = useState<Tab>('library');

  return (
    <div className="h-full flex flex-col">
      <div className="h-12 shrink-0 border-b border-[var(--border-soft)] flex items-center px-4 gap-1">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
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
        <Panes
          active={tab}
          className="h-full"
          panes={[
            { id: 'library', render: () => <ModelsLibrary /> },
            { id: 'quantize', render: () => <CapabilityGate names="quantize"><QuantizeView /></CapabilityGate> },
            { id: 'train', render: () => <CapabilityGate names="train"><TrainingView /></CapabilityGate> },
          ]}
        />
      </div>
    </div>
  );
}
