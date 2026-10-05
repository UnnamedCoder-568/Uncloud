import AutomationsPanel from '../components/AutomationsPanel';

export default function AutomationsView() {
  return (
    <div className="h-full overflow-y-auto chassis-scroll">
      <div className="mx-auto max-w-4xl px-6 py-6">
        <header className="mb-6">
          <h1 className="text-2xl font-semibold mb-2">Automations</h1>
          <p className="text-sm text-[var(--text-faint)]">
            Save an agent, choose when it runs, and review its progress here.
          </p>
        </header>
        <AutomationsPanel />
      </div>
    </div>
  );
}
