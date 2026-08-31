import { useState } from 'react';
import Wordmark from './Wordmark';
import { MessageSquare, Boxes, Workflow, ImageIcon, Clapperboard, Mic, Music, Settings, HelpCircle, ChevronLeft, ChevronRight } from 'lucide-react';

export type View = 'chat' | 'models' | 'agent' | 'image' | 'video' | 'music' | 'voice' | 'guide' | 'settings';

const items: { id: View; label: string; icon: React.ComponentType<{ size?: number; strokeWidth?: number; className?: string }> }[] = [
  { id: 'chat', label: 'Chat', icon: MessageSquare },
  { id: 'models', label: 'Models', icon: Boxes },
  { id: 'agent', label: 'Agent', icon: Workflow },
  { id: 'image', label: 'Image', icon: ImageIcon },
  { id: 'video', label: 'Video', icon: Clapperboard },
  { id: 'music', label: 'Music', icon: Music },
  { id: 'voice', label: 'Voice', icon: Mic },
];

function loadExpanded(): boolean {
  return localStorage.getItem('uncloud-sidebar-expanded') !== 'false';
}

export default function Sidebar({ active, onChange }: { active: View; onChange: (v: View) => void }) {
  const [expanded, setExpanded] = useState(loadExpanded);

  function toggle() {
    setExpanded((v) => {
      const next = !v;
      localStorage.setItem('uncloud-sidebar-expanded', String(next));
      return next;
    });
  }

  return (
    <div
      className={`shrink-0 h-full bg-[var(--bg-inset)] border-r border-[var(--border-soft)] flex flex-col pt-12 pb-4 gap-1 transition-[width] duration-150 ${
        expanded ? 'w-[210px] px-3' : 'w-[68px] items-center'
      }`}
      data-tauri-drag-region
    >
      <div className={`flex items-center gap-2 mb-4 ${expanded ? 'px-1' : 'justify-center'}`}>
        {expanded ? (
          <Wordmark size={20} />
        ) : (
          <Wordmark size={20} className="[&>span]:hidden" />
        )}
      </div>

      {items.map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          onClick={() => onChange(id)}
          title={label}
          className={`h-11 rounded-xl flex items-center transition ${expanded ? 'px-3 gap-3 w-full' : 'w-11 justify-center'} ${
            active === id
              ? 'bg-[var(--bg-raised)] text-white border border-[var(--border)]'
              : 'text-[var(--text-faint)] hover:text-[var(--text-dim)] hover:bg-[var(--bg-raised)]/50 border border-transparent'
          }`}
        >
          <Icon size={18} strokeWidth={1.75} className="shrink-0" />
          {expanded && <span className="text-sm">{label}</span>}
        </button>
      ))}

      <div className="flex-1" />

      <button
        onClick={() => onChange('guide')}
        title="Guide"
        className={`h-11 rounded-xl flex items-center transition ${expanded ? 'px-3 gap-3 w-full' : 'w-11 justify-center'} ${
          active === 'guide'
            ? 'bg-[var(--bg-raised)] text-white border border-[var(--border)]'
            : 'text-[var(--text-faint)] hover:text-[var(--text-dim)] hover:bg-[var(--bg-raised)]/50 border border-transparent'
        }`}
      >
        <HelpCircle size={18} strokeWidth={1.75} className="shrink-0" />
        {expanded && <span className="text-sm">Guide</span>}
      </button>

      <button
        onClick={() => onChange('settings')}
        title="Settings"
        className={`h-11 rounded-xl flex items-center transition ${expanded ? 'px-3 gap-3 w-full' : 'w-11 justify-center'} ${
          active === 'settings'
            ? 'bg-[var(--bg-raised)] text-white border border-[var(--border)]'
            : 'text-[var(--text-faint)] hover:text-[var(--text-dim)] hover:bg-[var(--bg-raised)]/50 border border-transparent'
        }`}
      >
        <Settings size={18} strokeWidth={1.75} className="shrink-0" />
        {expanded && <span className="text-sm">Settings</span>}
      </button>

      <button
        onClick={toggle}
        title={expanded ? 'Collapse sidebar' : 'Expand sidebar'}
        className={`h-9 rounded-xl flex items-center text-[var(--text-faint)] hover:text-[var(--text-dim)] hover:bg-[var(--bg-raised)]/50 transition mt-1 ${
          expanded ? 'px-3 gap-3 w-full justify-start' : 'w-11 justify-center'
        }`}
      >
        {expanded ? <ChevronLeft size={16} /> : <ChevronRight size={16} />}
        {expanded && <span className="text-xs">Collapse</span>}
      </button>
    </div>
  );
}
