/** The left rail.
 *
 *  Laid out to the shared chassis: 260px, 36px rows, uppercase section labels,
 *  identity pinned to the bottom. See docs/DESIGN-LANGUAGE.md.
 *
 *  It hides entirely rather than collapsing to an icon strip. A 60px strip
 *  cannot clear the macOS traffic lights, so a collapsed rail would leave them
 *  straddling the boundary between two different background colours.
 */
import { useState } from 'react';
import type { ReactNode } from 'react';
import Wordmark from './Wordmark';
import {
  MessageSquare, Boxes, Workflow, ImageIcon, Clapperboard, Mic, Music,
  Settings, HelpCircle, FolderOpen,
} from 'lucide-react';

export type View =
  | 'chat' | 'models' | 'chisel' | 'image' | 'video' | 'music' | 'voice'
  | 'outputs' | 'guide' | 'settings';

type Icon = React.ComponentType<{ size?: number; strokeWidth?: number }>;

const GROUPS: { label?: string; items: { id: View; label: string; icon: Icon }[] }[] = [
  {
    items: [
      { id: 'chat', label: 'Chat', icon: MessageSquare },
      { id: 'models', label: 'Models', icon: Boxes },
      { id: 'chisel', label: 'Chisel', icon: Workflow },
    ],
  },
  {
    label: 'Create',
    items: [
      { id: 'image', label: 'Image', icon: ImageIcon },
      { id: 'video', label: 'Video', icon: Clapperboard },
      { id: 'music', label: 'Music', icon: Music },
      { id: 'voice', label: 'Voice', icon: Mic },
    ],
  },
  {
    label: 'Library',
    items: [{ id: 'outputs', label: 'Outputs', icon: FolderOpen }],
  },
];

const FOOT: { id: View; label: string; icon: Icon }[] = [
  { id: 'guide', label: 'Guide', icon: HelpCircle },
  { id: 'settings', label: 'Settings', icon: Settings },
];

function Row({ item, active, onChange }: {
  item: { id: View; label: string; icon: Icon };
  active: View;
  onChange: (v: View) => void;
}) {
  const { id, label, icon: Icon } = item;
  return (
    <button
      onClick={() => onChange(id)}
      title={label}
      aria-current={active === id ? 'page' : undefined}
      className={active === id ? 'rail-row rail-row-active' : 'rail-row'}
    >
      <Icon size={18} strokeWidth={1.75} />
      <span>{label}</span>
    </button>
  );
}

export default function Sidebar({ active, onChange, top }: {
  active: View;
  onChange: (v: View) => void;
  /** The window's title strip. The rail owns the left half of it. */
  top: ReactNode;
}) {
  const [hovered, setHovered] = useState(false);

  return (
    <nav
      className="rail"
      // The cog in the wordmark punches its holes in var(--bg). On the rail
      // that would be the wrong grey by one step, so --bg is re-pointed at the
      // rail's own colour for the subtree.
      style={{ '--bg': 'var(--sidebar)' } as React.CSSProperties}
    >
      {top}

      <div style={{ padding: '4px 16px 12px' }}>
        <Wordmark size={19} />
      </div>

      <div className="rail-body chassis-scroll">
        {GROUPS.map((group, i) => (
          <div key={group.label ?? i}>
            {group.label && <div className="rail-label">{group.label}</div>}
            {group.items.map((item) => (
              <Row key={item.id} item={item} active={active} onChange={onChange} />
            ))}
          </div>
        ))}
      </div>

      <div style={{ padding: '0 8px 4px' }}>
        {FOOT.map((item) => (
          <Row key={item.id} item={item} active={active} onChange={onChange} />
        ))}
      </div>

      {/* Identity. Nothing is signed in to — that is the product — so it says
          so rather than showing an account that does not exist. */}
      <div
        className="rail-foot"
        onClick={() => onChange('settings')}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') onChange('settings'); }}
        title="Settings"
      >
        <span className="rail-avatar">U</span>
        <span className="rail-foot-text">
          <b>Uncloud</b>
          <small>{hovered ? 'Settings' : 'Running on this machine'}</small>
        </span>
      </div>
    </nav>
  );
}
