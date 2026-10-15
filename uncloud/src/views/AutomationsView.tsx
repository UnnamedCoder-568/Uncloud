import AutomationsPanel from '../components/AutomationsPanel';
import { useState } from 'react';
import Panes from '../components/Panes';
import RecipesView from './RecipesView';

export default function AutomationsView() {
  const [tab, setTab] = useState('agents');
  return (
    <div className="h-full flex flex-col">
      <div className="mx-auto w-full max-w-4xl px-6 pt-6">
        <header className="mb-4">
          <h1 className="text-2xl font-semibold mb-2">Automations</h1>
          <p className="text-sm text-[var(--text-faint)]">
            Schedule agents and keep reusable recipes in one place.
          </p>
        </header>
        <div className="flex gap-2 pb-4" role="tablist" aria-label="Automations">
          {[['agents', 'Agents & schedules'], ['recipes', 'Recipes']].map(([id, label]) => (
            <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
              className={tab === id ? 'pill pill-on' : 'pill'}>{label}</button>
          ))}
        </div>
      </div>
      <Panes active={tab} className="flex-1 min-h-0" panes={[
        { id: 'agents', render: () => <div className="h-full overflow-y-auto chassis-scroll"><div className="mx-auto max-w-4xl px-6 pb-6"><AutomationsPanel /></div></div> },
        { id: 'recipes', render: () => <RecipesView /> },
      ]} />
    </div>
  );
}
