/**
 * A settings column beside its result — both at once on a desktop, one at a
 * time on a phone.
 *
 * The arrangement is entirely CSS (`.split` in the chassis). This only holds
 * which pane a phone is looking at, and moves it to the result when work
 * starts: pressing Generate on a phone and then having to find the tab that
 * shows what it made is the kind of small friction that makes a surface feel
 * like an afterthought.
 */

import { useEffect, useState } from 'react';

export interface SplitState {
  pane: number;
  setPane: (pane: number) => void;
  /** The class suffix for pane `i`: present only on the pane being shown. */
  on: (i: number) => string;
}

export function useSplit(working: boolean): SplitState {
  const [pane, setPane] = useState(0);
  useEffect(() => { if (working) setPane(1); }, [working]);
  return { pane, setPane, on: (i) => (pane === i ? ' split-pane-on' : '') };
}

/** Hidden above the breakpoint by the chassis, so it costs a desktop nothing. */
export function SplitTabs({ split, labels }: { split: SplitState; labels: string[] }) {
  return (
    <div className="split-tabs" role="tablist">
      {labels.map((label, i) => (
        <button
          key={label}
          type="button"
          role="tab"
          aria-selected={split.pane === i}
          className="split-tab"
          onClick={() => split.setPane(i)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
