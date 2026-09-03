/** The strip along the top of the window.
 *
 *  macOS runs the window with titleBarStyle "Overlay", so the traffic lights
 *  float over our own chrome and this 44px strip is ours to lay out:
 *
 *      [ lights ] [ ☰ ] [ ← → ]      [ context ]      [ actions ]
 *
 *  The whole strip drags the window. Every control inside it opts out with
 *  .no-drag — the chassis does that for .tb-btn and .tb-context — because a
 *  button that has stayed draggable is indistinguishable from a hung app.
 *
 *  With the rail open there are two aligned strips: one inside the rail
 *  holding the controls, one over the main area holding the context. With the
 *  rail hidden there is one strip holding both, and it takes the inset for the
 *  traffic lights.
 */
import { createContext, useContext } from 'react';
import { createPortal } from 'react-dom';
import { PanelLeft, ChevronLeft, ChevronRight } from 'lucide-react';
import type { ReactNode } from 'react';

/** The title bar's centre slot.
 *
 *  A view owns its own context — Chat knows which model is loaded, Image knows
 *  which checkpoint — but the place to show it is the window title bar, which
 *  the view does not own. So the shell exposes the element and views portal
 *  into it.
 *
 *  Panes stay mounted after their first visit, so the slot is handed only to
 *  the ACTIVE pane. Give it to all of them and every visited view renders its
 *  context into the title bar at once; `hidden` on the pane will not help,
 *  because portalled content is not inside the pane any more. */
const SlotContext = createContext<HTMLElement | null>(null);

export const TitleBarSlot = SlotContext.Provider;

export function TitleBarPortal({ children }: { children: ReactNode }) {
  const slot = useContext(SlotContext);
  return slot ? createPortal(children, slot) : null;
}

/** Just the buttons. Deliberately not wrapped in a strip of their own, so the
 *  caller decides which strip they belong to. */
export function NavControls({
  railOpen, onToggleRail, onBack, onForward, canBack, canForward,
}: {
  railOpen: boolean;
  onToggleRail: () => void;
  onBack: () => void;
  onForward: () => void;
  canBack: boolean;
  canForward: boolean;
}) {
  return (
    <>
      <button
        className="tb-btn"
        onClick={onToggleRail}
        title={railOpen ? 'Hide sidebar' : 'Show sidebar'}
        aria-label={railOpen ? 'Hide sidebar' : 'Show sidebar'}
      >
        <PanelLeft size={17} strokeWidth={1.75} />
      </button>
      <button className="tb-btn" onClick={onBack} disabled={!canBack}
              title="Back" aria-label="Back">
        <ChevronLeft size={18} strokeWidth={1.75} />
      </button>
      <button className="tb-btn" onClick={onForward} disabled={!canForward}
              title="Forward" aria-label="Forward">
        <ChevronRight size={18} strokeWidth={1.75} />
      </button>
    </>
  );
}

export default function TitleBar({ inset = false, children, actions }: {
  /** Reserve room for the traffic lights. Exactly one strip should do this. */
  inset?: boolean;
  children?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className={inset ? 'titlebar titlebar-pad' : 'titlebar'}>
      {children}
      <div style={{ flex: 1 }} />
      {actions}
    </div>
  );
}
