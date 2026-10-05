import CapabilityGate from '../components/CapabilityGate';
import { Talk } from './VoiceToVoice';

export default function FridayView() {
  return <div className="h-full flex flex-col">
    <header className="px-6 pt-5 pb-3 border-b border-[var(--border-soft)]">
      <h1 className="page-title">Friday</h1>
      <p className="text-sm text-[var(--text-dim)] mt-2">Your local voice companion. Calm, capable, with a little wit.</p>
      <p className="text-xs text-[var(--text-faint)] mt-1">Choose a model and voice, then start talking. For tools and computer actions, use Chisel.</p>
    </header>
    <div className="flex-1 min-h-0"><CapabilityGate names="chat,transcribe,kokoro"><Talk friday /></CapabilityGate></div>
  </div>;
}
