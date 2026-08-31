import { useCallback, useEffect, useState } from 'react';
import Sidebar from './components/Sidebar';
import type { View } from './components/Sidebar';
import Onboarding from './views/Onboarding';
import ChatView from './views/ChatView';
import ModelsView from './views/ModelsView';
import AgentView from './views/AgentView';
import SettingsView from './views/SettingsView';
import ImageView from './views/ImageView';
import VoiceView from './views/VoiceView';
import MusicView from './views/MusicView';
import VideoView from './views/VideoView';
import GuideView from './views/GuideView';
import SetupView from './views/SetupView';
import { getSettings, runtimeStatus } from './lib/sidecar';
import Wordmark from './components/Wordmark';

export default function App() {
  // null while we're still asking; false sends the user to setup.
  const [engineUp, setEngineUp] = useState<boolean | null>(null);
  const [ready, setReady] = useState(false);
  const [onboarded, setOnboarded] = useState(false);
  const [view, setView] = useState<View>('chat');
  const [engineError, setEngineError] = useState<string | null>(null);

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

  const handleEngineReady = useCallback(() => setEngineUp(true), []);

  const splash = (
    <div className="h-screen w-screen flex items-center justify-center">
      <Wordmark size={40} spinning />
    </div>
  );

  if (engineUp === null) return splash;
  if (!engineUp) return <SetupView onReady={handleEngineReady} />;

  if (engineError) {
    return (
      <div className="h-screen w-screen flex items-center justify-center text-sm text-rose-400 px-8 text-center">
        Uncloud engine failed to start: {engineError}
      </div>
    );
  }

  if (!ready) return splash;

  if (!onboarded) {
    return <Onboarding onDone={() => setOnboarded(true)} />;
  }

  return (
    <div className="h-screen w-screen flex bg-[var(--bg)]">
      <Sidebar active={view} onChange={setView} />
      <main className="flex-1 min-w-0">
        {view === 'chat' && <ChatView />}
        {view === 'models' && <ModelsView />}
        {view === 'agent' && <AgentView />}
        {view === 'guide' && <GuideView />}
        {view === 'settings' && <SettingsView />}
        {view === 'image' && <ImageView />}
        {view === 'video' && <VideoView />}
        {view === 'music' && <MusicView />}
        {view === 'voice' && <VoiceView />}
      </main>
    </div>
  );
}
