import ActivityOrb from './components/ActivityOrb';
import { useCallback, useEffect, useMemo, useState } from 'react';
import Sidebar from './components/Sidebar';
import type { View } from './components/Sidebar';
import TitleBar, { NavControls, TitleBarSlot } from './components/TitleBar';
import Panes from './components/Panes';
import { onHandoffSignal } from './lib/handoff';
import Onboarding from './views/Onboarding';
import TermsView from './views/TermsView';
import ApprovalPrompt from './components/ApprovalPrompt';
import ChatView from './views/ChatView';
import ModelsView from './views/ModelsView';
import ChiselView from './views/ChiselView';
import SettingsView from './views/SettingsView';
import RecipesView from './views/RecipesView';
import ImageView from './views/ImageView';
import VoiceView from './views/VoiceView';
import MusicView from './views/MusicView';
import VideoView from './views/VideoView';
import GuideView from './views/GuideView';
import OutputsView from './views/OutputsView';
import SetupView from './views/SetupView';
import { getLegalState, getSettings, runtimeStatus } from './lib/sidecar';
import Wordmark from './components/Wordmark';
import { inDesktop, useNarrow } from './lib/platform';
import UpdateBanner from './components/UpdateBanner';
import { AddFromDiskHost } from './components/AddFromDisk';


/** Rendered once visited, then kept alive so tab switching is not destructive. */
const PANES: { id: View; render: () => React.ReactElement }[] = [
  { id: 'chat', render: () => <ChatView /> },
  { id: 'models', render: () => <ModelsView /> },
  { id: 'chisel', render: () => <ChiselView /> },
  { id: 'image', render: () => <ImageView /> },
  { id: 'video', render: () => <VideoView /> },
  { id: 'music', render: () => <MusicView /> },
  { id: 'voice', render: () => <VoiceView /> },
  { id: 'outputs', render: () => <OutputsView /> },
  { id: 'guide', render: () => <GuideView /> },
  { id: 'recipes', render: () => <RecipesView /> },
  { id: 'settings', render: () => <SettingsView /> },
];

/** Where the rail was left last time. Reopening to a hidden rail that the user
 *  never chose to hide is disorienting, so the choice is remembered. */
function loadRailOpen(): boolean {
  try { return localStorage.getItem('uncloud.rail') !== 'closed'; }
  catch { return true; }
}

export default function App() {
  // null while we're still asking; false sends the user to setup.
  const [engineUp, setEngineUp] = useState<boolean | null>(null);
  const [ready, setReady] = useState(false);
  const [onboarded, setOnboarded] = useState(false);
  const [settled, setSettled] = useState<boolean | null>(null);
  const [engineError, setEngineError] = useState<string | null>(null);
  const [railOpen, setRailOpen] = useState(loadRailOpen);
  const [slot, setSlot] = useState<HTMLDivElement | null>(null);

  // Real history, so the title bar's arrows do something. Kept as ONE piece of
  // state: a stack and a position updated by two separate setters can disagree
  // for a render, and the disagreement shows up as the wrong pane.
  const [nav, setNav] = useState<{ stack: View[]; at: number }>(
    { stack: ['chat'], at: 0 });
  const view = nav.stack[nav.at];

  const setView = useCallback((next: View) => {
    setNav((n) => {
      if (n.stack[n.at] === next) return n;
      // Navigating from the middle drops what was ahead, as a browser does.
      const stack = [...n.stack.slice(0, n.at + 1), next];
      return { stack, at: stack.length - 1 };
    });
  }, []);

  // Handing a conversation to Chisel takes you there. Filling a field on a
  // screen the user is not looking at is indistinguishable from nothing having
  // happened. It goes through the nav stack like any other move, so Back
  // returns to the conversation.
  useEffect(() => onHandoffSignal(() => setView('chisel')), [setView]);

  const goBack = useCallback(
    () => setNav((n) => (n.at > 0 ? { ...n, at: n.at - 1 } : n)), []);
  const goForward = useCallback(
    () => setNav((n) => (n.at < n.stack.length - 1 ? { ...n, at: n.at + 1 } : n)), []);

  // On a phone the rail is a drawer: closed to begin with, closed again after
  // every move, and never written into the desktop's remembered preference —
  // closing it on a phone must not hide it the next time the app opens.
  const narrow = useNarrow();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const showRail = narrow ? drawerOpen : railOpen;
  const go = useCallback((next: View) => {
    setView(next);
    setDrawerOpen(false);
  }, [setView]);

  const toggleRail = useCallback(() => {
    if (narrow) {
      setDrawerOpen((open) => !open);
      return;
    }
    setRailOpen((open) => {
      try { localStorage.setItem('uncloud.rail', open ? 'closed' : 'open'); }
      catch { /* private window; the default is fine */ }
      return !open;
    });
  }, [narrow]);

  const controls = useMemo(() => (
    <NavControls
      railOpen={showRail}
      onToggleRail={toggleRail}
      onBack={goBack}
      onForward={goForward}
      canBack={nav.at > 0}
      canForward={nav.at < nav.stack.length - 1}
    />
  ), [showRail, toggleRail, goBack, goForward, nav.at, nav.stack.length]);

  useEffect(() => {
    runtimeStatus()
      .then((s) => setEngineUp(s.running))
      .catch(() => setEngineUp(false));
  }, []);

  useEffect(() => {
    if (!engineUp) return;
    getSettings()
      .then((s) => {
        setOnboarded(s.onboarded);
        setReady(true);
      })
      .catch((e) => setEngineError(String(e)));
  }, [engineUp]);

  // Asked before anything else, including onboarding: choosing a models folder
  // and downloading weights are both things the terms cover.
  useEffect(() => {
    if (!engineUp) return;
    getLegalState()
      .then((s) => setSettled(s.settled))
      // An engine too old to know about terms must not lock the application
      // out of itself. A missing endpoint is not an unsigned agreement.
      .catch(() => setSettled(true));
  }, [engineUp]);

  const handleEngineReady = useCallback(() => setEngineUp(true), []);

  const splash = (
    <div className="h-screen w-screen flex items-center justify-center dot-ground">
      <div className="glow flex flex-col items-center gap-4">
        <ActivityOrb state="connecting" size={64} label="Starting Uncloud…" />
        <Wordmark size={32} />
        <span className="text-xs text-[var(--text-faint)]">Starting Uncloud…</span>
      </div>
    </div>
  );

  // Mounted before any branch returns, so a request that needs a decision
  // during setup or onboarding still has somewhere to be answered.
  if (engineUp === null) return <>{splash}<ApprovalPrompt /></>;
  if (!engineUp) return <><SetupView onReady={handleEngineReady} /><ApprovalPrompt /></>;

  if (engineError) {
    return (
      <div className="h-screen w-screen flex items-center justify-center text-sm text-rose-400 px-8 text-center">
        Uncloud engine failed to start: {engineError}
      </div>
    );
  }

  if (!ready) return splash;

  if (settled === null) return splash;
  if (!settled) return <TermsView onSettled={() => setSettled(true)} />;

  if (!onboarded) {
    // Choosing where models and work live is a question about the computer's
    // disk. A paired phone is told so, rather than shown folder pickers that
    // cannot work.
    if (!inDesktop()) {
      return (
        <div className="h-dvh w-screen flex flex-col items-center justify-center gap-3 px-8 text-center">
          <Wordmark size={32} />
          <p className="text-sm text-[var(--text-dim)] max-w-xs leading-relaxed">
            Finish setting up Uncloud on the computer it runs on, then reload this page.
          </p>
        </div>
      );
    }
    return <><Onboarding onDone={() => setOnboarded(true)} /><ApprovalPrompt /></>;
  }

  return (
    <div className="h-screen w-screen flex bg-[var(--bg)]">
      {showRail && narrow && (
        <div className="rail-scrim" onClick={() => setDrawerOpen(false)} />
      )}
      {showRail && (
        <Sidebar
          active={view}
          onChange={go}
          top={<TitleBar inset>{controls}</TitleBar>}
        />
      )}
      <main className="flex-1 min-w-0 flex flex-col">
        {/* With the rail hidden this is the only strip, so it takes the inset
            for the traffic lights and carries the navigation controls too. */}
        {/* On a phone the drawer lies over this strip rather than replacing
            it, so the controls stay here whether or not it is open. */}
        <TitleBar inset={!showRail || narrow}>
          {(!showRail || narrow) && controls}
          <div ref={setSlot} className="flex items-center gap-1 flex-1 min-w-0" />
        </TitleBar>
        <UpdateBanner />
        <Panes
          active={view}
          panes={PANES}
          className="flex-1 min-h-0"
          // Only the visible pane may write to the title bar. Portalled content
          // is not inside the pane, so `hidden` would not stop it.
          wrap={(pane, isActive) => (
            <TitleBarSlot value={isActive ? slot : null}>{pane}</TitleBarSlot>
          )}
        />
      </main>
      <ApprovalPrompt />
      <AddFromDiskHost />
    </div>
  );
}
