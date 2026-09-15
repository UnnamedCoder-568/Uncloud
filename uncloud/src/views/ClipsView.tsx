import { useCallback, useEffect, useState } from 'react';
import { Check, Loader2, Pencil, Play, X } from 'lucide-react';
import { renameClip, speechClips, speechClipUrl } from '../lib/sidecar';
import type { SpeechClip } from '../lib/sidecar';
import SaveActions from '../components/SaveActions';
import { useWhenVisible } from '../components/Panes';

/**
 * Everything spoken: text to voice, narration, conversions, and replies read
 * aloud in Chat and Chisel.
 *
 * All of it is already on disk in the output folder. This is where it can be
 * found again, named, played, and saved somewhere else — which is what "save
 * that voice" meant when a good take went by in a conversation.
 */

const KINDS: { id: string; label: string }[] = [
  { id: '', label: 'All' },
  { id: 'speech', label: 'Text to voice' },
  { id: 'narration', label: 'Narration' },
  { id: 'conversion', label: 'Converted' },
  { id: 'reply', label: 'Replies' },
];

function when(seconds: number): string {
  return new Date(seconds * 1000).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

export default function ClipsView() {
  const [kind, setKind] = useState('');
  const [clips, setClips] = useState<SpeechClip[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState<{ id: string; url: string } | null>(null);
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);

  const load = useCallback(() => {
    speechClips(kind).then(setClips).catch((e) => setError(String(e)));
  }, [kind]);
  useEffect(() => { load(); }, [load]);
  // New clips are made in other tabs while this one waits hidden.
  useWhenVisible(load);

  async function play(clip: SpeechClip) {
    try {
      if (playing) URL.revokeObjectURL(playing.url);
      setPlaying({ id: clip.id, url: await speechClipUrl(clip.id) });
    } catch (e) {
      setError(String(e));
    }
  }

  async function rename() {
    if (!renaming?.name.trim()) return;
    try {
      await renameClip(renaming.id, renaming.name.trim());
      setRenaming(null);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="h-full overflow-y-auto px-6 py-5">
      <div className="max-w-3xl flex flex-col gap-4">
        <div className="flex gap-1 flex-wrap">
          {KINDS.map((k) => (
            <button key={k.id} onClick={() => setKind(k.id)} className={kind === k.id ? 'pill pill-on' : 'pill'}>
              <span>{k.label}</span>
            </button>
          ))}
        </div>
        {error && <p className="text-[11px] text-rose-400">{error}</p>}
        {clips === null ? (
          <Loader2 size={16} className="animate-spin text-[var(--text-faint)]" />
        ) : clips.length === 0 ? (
          <p className="text-sm text-[var(--text-faint)] leading-relaxed">
            Nothing here yet. Everything you make in Text to voice, Narration and Voice to
            voice lands here, and so does every reply read aloud in Chat or Chisel.
          </p>
        ) : clips.map((clip) => (
          <div key={clip.id} className="card p-3.5 flex flex-col gap-2.5">
            <div className="flex items-start gap-3">
              <button onClick={() => play(clip)} aria-label={`Play ${clip.name}`}
                      className="w-8 h-8 shrink-0 rounded-full bg-[var(--bg-raised)] hover:bg-[var(--bg-inset)] flex items-center justify-center">
                <Play size={13} />
              </button>
              <div className="min-w-0 flex-1">
                {renaming?.id === clip.id ? (
                  <div className="flex gap-1.5">
                    <input autoFocus value={renaming.name}
                           onChange={(e) => setRenaming({ id: clip.id, name: e.target.value })}
                           onKeyDown={(e) => { if (e.key === 'Enter') void rename(); if (e.key === 'Escape') setRenaming(null); }}
                           className="flex-1 min-w-0 text-sm px-2 py-1 rounded-md bg-[var(--bg-inset)] outline-none" />
                    <button onClick={rename} aria-label="Save name" className="px-1.5 text-[var(--text-dim)]"><Check size={14} /></button>
                    <button onClick={() => setRenaming(null)} aria-label="Cancel" className="px-1.5 text-[var(--text-faint)]"><X size={14} /></button>
                  </div>
                ) : (
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-sm truncate">{clip.name}</span>
                    <button onClick={() => setRenaming({ id: clip.id, name: clip.name })}
                            aria-label="Rename" className="text-[var(--text-faint)] hover:text-[var(--text-dim)] shrink-0">
                      <Pencil size={11} />
                    </button>
                  </div>
                )}
                <p className="text-[10px] text-[var(--text-faint)] mt-0.5 tabular-nums">
                  {when(clip.created)}
                  {clip.duration ? ` · ${clip.duration.toFixed(1)}s` : ''}
                  {clip.voice ? ` · ${clip.voice}` : ''}
                  {clip.engine ? ` · ${clip.engine}` : ''}
                </p>
                {clip.text && <p className="text-[11px] text-[var(--text-dim)] mt-1 line-clamp-2">{clip.text}</p>}
              </div>
            </div>
            {playing?.id === clip.id && <audio src={playing.url} controls autoPlay className="w-full h-9" />}
            <SaveActions path={clip.path} onDiscarded={load} />
          </div>
        ))}
      </div>
    </div>
  );
}
