import { useState } from 'react';
import Panes from '../components/Panes';
import ImageGenerate from './ImageGenerate';
import ProductStudio from './ProductStudio';
import ImageEdit from './ImageEdit';
import CharactersView from './CharactersView';

type Tab = 'generate' | 'product' | 'edit' | 'characters';

const TABS: { id: Tab; label: string }[] = [
  { id: 'generate', label: 'Generate' },
  { id: 'product', label: 'Product' },
  { id: 'edit', label: 'Edit' },
  { id: 'characters', label: 'Characters' },
];

export default function ImageView() {
  const [tab, setTab] = useState<Tab>('generate');

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
            { id: 'generate', render: () => <ImageGenerate /> },
            { id: 'product', render: () => <ProductStudio /> },
            { id: 'edit', render: () => <ImageEdit /> },
            { id: 'characters', render: () => <CharactersView /> },
          ]}
        />
      </div>
    </div>
  );
}
