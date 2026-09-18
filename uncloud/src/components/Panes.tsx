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

import { Component, createContext, useContext, useEffect, useRef, useState } from 'react';
import type { ErrorInfo, ReactNode } from 'react';

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

interface BoundaryState { error: Error | null; details: string }

/** A screen that throws while it draws stays that screen's problem.
 *
 *  React unmounts everything above an error nobody catches. With no boundary
 *  in the application, one unexpected value in one screen — a list where a
 *  path was expected — left the whole window blank, with no way back but to
 *  quit: the sidebar went with it, so there was nothing left to click.
 *
 *  Every pane is wrapped in one of these, so a failure shows as a panel in
 *  place of that screen while the rest keeps working, and `whole` wraps the
 *  application itself as the last resort. Styled only with the chassis tokens,
 *  because this file is shared between both products and has to look right in
 *  each without either one's stylesheet.
 */
export class ScreenBoundary extends Component<
  { children: ReactNode; whole?: boolean }, BoundaryState
> {
  state: BoundaryState = { error: null, details: '' };

  static getDerivedStateFromError(error: Error): Partial<BoundaryState> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Kept for "Copy details": a bug report with the component stack in it is
    // one that can be fixed without a way to reproduce it.
    this.setState({
      details: `${error.name}: ${error.message}\n${info.componentStack ?? ''}`.trim(),
    });
    console.error(error, info.componentStack);
  }

  private retry = () => {
    if (this.props.whole) window.location.reload();
    else this.setState({ error: null, details: '' });
  };

  private copy = () => {
    const { error, details } = this.state;
    void navigator.clipboard?.writeText(details || error?.message || '').catch(() => undefined);
  };

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    const whole = this.props.whole;
    const button = {
      font: 'inherit', fontSize: 13, padding: '6px 14px', borderRadius: 8, cursor: 'pointer',
      border: '1px solid var(--border-strong)', background: 'var(--surface)', color: 'var(--text)',
    } as const;
    return (
      <div role="alert" style={{
        margin: whole ? '15vh auto' : '48px auto', maxWidth: 520, padding: 24,
        borderRadius: 12, border: '1px solid var(--border)', background: 'var(--surface-sunken)',
        color: 'var(--text)', fontSize: 14, lineHeight: 1.5,
      }}>
        <div style={{ fontSize: 16, fontWeight: 600 }}>
          {whole ? 'Something went wrong' : 'This screen ran into a problem'}
        </div>
        <p style={{ margin: '8px 0 12px', color: 'var(--text-2)' }}>
          {whole
            ? 'Reloading usually clears it. Everything you have saved is on disk and safe.'
            : 'The rest of the app still works, and everything you have saved is safe. '
              + 'Try again, or open another screen.'}
        </p>
        <code style={{
          display: 'block', fontSize: 12, padding: '8px 10px', borderRadius: 8,
          background: 'var(--bg)', color: 'var(--text-3)', overflowWrap: 'anywhere',
        }}>
          {error.message || error.name}
        </code>
        <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
          <button type="button" style={button} onClick={this.retry}>
            {whole ? 'Reload' : 'Try again'}
          </button>
          <button type="button" style={{ ...button, background: 'transparent' }} onClick={this.copy}>
            Copy details
          </button>
        </div>
      </div>
    );
  }
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
              {wrap
                ? wrap(<ScreenBoundary>{render()}</ScreenBoundary>, isActive)
                : <ScreenBoundary>{render()}</ScreenBoundary>}
            </VisibleContext.Provider>
          </div>
        );
      })}
    </>
  );
}
