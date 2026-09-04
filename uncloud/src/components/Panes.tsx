/** Tab panes that survive being switched away from.
 *
 *  Rendering a view with `active === id && <View/>` unmounts it the moment
 *  someone looks at something else, and React state goes with it: a prompt
 *  half-written, options chosen, a filter set, a job still running. Checking
 *  one thing in another tab should not cost you the sentence you were writing.
 *
 *  So a pane is mounted on first visit and kept mounted afterwards, hidden
 *  rather than destroyed. Nothing is mounted before it is first needed, which
 *  is what keeps a cold start cheap.
 *
 *  The cost, which is real: a pane that stays mounted also stays STALE. It
 *  holds whatever it read when it first appeared, and a list of assets or
 *  models that changed while the user was elsewhere never catches up — which
 *  reads as a broken feature rather than an old one. `useWhenVisible` is the
 *  answer to that, and any pane showing data the rest of the app can change
 *  should use it.
 */

import { createContext, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';

export interface Pane<T extends string> {
  id: T;
  render: () => ReactNode;
}

const VisibleContext = createContext<boolean>(true);

/** Run something each time this pane becomes visible again — not on the first
 *  mount, which the pane's own effects already cover. */
export function useWhenVisible(refresh: () => void): void {
  const visible = useContext(VisibleContext);
  const wasVisible = useRef(visible);
  const latest = useRef(refresh);
  latest.current = refresh;

  useEffect(() => {
    if (visible && !wasVisible.current) latest.current();
    wasVisible.current = visible;
  }, [visible]);
}

export default function Panes<T extends string>({ active, panes, className, wrap }: {
  active: T;
  panes: Pane<T>[];
  /** Applied to the visible pane's wrapper. */
  className?: string;
  /** Wraps each pane, told whether it is the visible one. Used to hand shared
   *  chrome — the title-bar slot — only to the pane on screen, because
   *  portalled content escapes `hidden` and every mounted pane would otherwise
   *  write into it at once. */
  wrap?: (pane: ReactNode, isActive: boolean) => ReactNode;
}) {
  // Adjusted during render rather than in an effect. React documents this for
  // deriving state from props: it re-runs this component before committing, so
  // nothing is painted twice, where an effect would queue a second render
  // after the first had already reached the screen.
  const [visited, setVisited] = useState<Set<T>>(() => new Set<T>([active]));
  if (!visited.has(active)) {
    setVisited(new Set(visited).add(active));
  }

  return (
    <>
      {panes.map(({ id, render }) => {
        if (!visited.has(id)) return null;
        const isActive = active === id;
        return (
          <div key={id} className={isActive ? className : undefined} hidden={!isActive}>
            <VisibleContext.Provider value={isActive}>
              {wrap ? wrap(render(), isActive) : render()}
            </VisibleContext.Provider>
          </div>
        );
      })}
    </>
  );
}
