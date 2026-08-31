import { useEffect, useState } from 'react';
import Sidebar from './components/Sidebar';
import type { View } from './components/Sidebar';
import Onboarding from './views/Onboarding';
import ChatView from './views/ChatView';
import ModelsView from './views/ModelsView';
import AgentView from './views/AgentView';
import SettingsView from './views/SettingsView';
import StudioView from './views/StudioView';
import ImageView from './views/ImageView';
import VoiceView from './views/VoiceView';
import MusicView from './views/MusicView';
import GuideView from './views/GuideView';
import { getSettings } from './lib/sidecar';
import Wordmark from './components/Wordmark';

export default function App() {
  const [ready, setReady] = useState(false);
  const [onboarded, setOnboarded] = useState(false);
  const [view, setView] = useState<View>('chat');
  const [engineError, setEngineError] = useState<string | null>(null);

  useEffect(() => {
    getSettings()
      .then((s) => {
        setOnboarded(s.onboarded);
        setReady(true);
      })
      .catch((e) => setEngineError(String(e)));
  }, []);

  if (engineError) {
    return (
      <div className="h-screen w-screen flex items-center justify-center text-sm text-rose-400 px-8 text-center">
        Uncloud engine failed to start: {engineError}
      </div>
    );
  }

  if (!ready) {
    return (
      <div className="h-screen w-screen flex items-center justify-center">
        <Wordmark size={40} spinning />
      </div>
    );
  }

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
        {view === 'video' && (
          <StudioView
            title="Video"
            subtitle="Text-to-video and image-to-video generation."
            categories={['video']}
            placeholder="A slow drone shot over a foggy forest…"
          />
        )}
        {view === 'music' && <MusicView />}
        {view === 'voice' && <VoiceView />}
      </main>
    </div>
  );
}
