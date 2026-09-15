import { useEffect, useState } from 'react';
import { savedVoices, VOICES } from '../lib/sidecar';
import type { SavedVoice } from '../lib/sidecar';

/**
 * Which voice reads replies aloud: one of Kokoro's, or any voice saved in
 * Voice. A saved voice is stored as `saved:<slug>`, so every surface that
 * speaks — Chat, Chisel, Voice to voice — shares one vocabulary.
 */

const ENGINE_NOTE: Record<string, string> = {
  chatterbox: 'Chatterbox · slower replies',
  bark: 'Bark · slow replies',
  kokoro: 'Kokoro',
};

/** The saved voices, read once per mount and whenever `refresh` changes. */
export function useSavedVoices(refresh = 0): SavedVoice[] {
  const [voices, setVoices] = useState<SavedVoice[]>([]);
  useEffect(() => {
    savedVoices().then((v) => setVoices(v.filter((x) => x.engine))).catch(() => setVoices([]));
  }, [refresh]);
  return voices;
}

export default function ReplyVoice({
  value,
  onChange,
  className = '',
  title = 'Voice for replies',
}: {
  value: string;
  onChange: (voice: string) => void;
  className?: string;
  title?: string;
}) {
  const saved = useSavedVoices();
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      title={title}
      className={className || 'text-xs px-2.5 py-2 rounded-lg bg-[var(--bg-inset)] outline-none'}
    >
      {saved.length > 0 && (
        <optgroup label="Your voices">
          {saved.map((v) => (
            <option key={v.slug} value={`saved:${v.slug}`}>
              {v.name} — {ENGINE_NOTE[v.engine] ?? v.engine}
            </option>
          ))}
        </optgroup>
      )}
      <optgroup label="Kokoro">
        {VOICES.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
      </optgroup>
      {value.startsWith('saved:') && !saved.some((v) => `saved:${v.slug}` === value) && (
        <option value={value}>A voice that was deleted</option>
      )}
    </select>
  );
}
