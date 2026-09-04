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
 */

import { useState } from 'react';
import type { ReactNode } from 'react';

export interface Pane<T extends string> {
  id: T;
  render: () => ReactNode;
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
      {panes.map(({ id, render }) =>
        visited.has(id) ? (
          <div key={id} className={active === id ? className : undefined}
               hidden={active !== id}>
            {wrap ? wrap(render(), active === id) : render()}
          </div>
        ) : null,
      )}
    </>
  );
}
