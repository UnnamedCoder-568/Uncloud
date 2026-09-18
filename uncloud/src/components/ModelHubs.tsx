import { ArrowUpRight, FolderPlus } from 'lucide-react';
import { openExternal } from '../lib/links';

/** Where else models come from, for the category being browsed.
 *
 *  The catalogue is a short, checked list — every entry has had its licence
 *  read and its files confirmed to load. The world is much larger than that,
 *  and a person who knows the model they want should be one press from where
 *  it lives, not sent to find it by themselves. Each hub opens already
 *  filtered to what this category runs: text is GGUF and MLX because those
 *  are the formats Uncloud loads, and a page of PyTorch checkpoints would be a
 *  list of things that cannot be used here.
 *
 *  Nothing is downloaded through these. The hub's own page, its own licence
 *  terms and its own gates apply, exactly as they would in a browser, and the
 *  file comes back into Uncloud through "Add a model you have".
 */

interface Hub { name: string; url: string; note: string }

const HF = 'https://huggingface.co/models';

const HUBS: Record<string, Hub[]> = {
  text: [
    { name: 'Hugging Face · GGUF', url: `${HF}?pipeline_tag=text-generation&library=gguf&sort=trending`,
      note: 'Runs everywhere' },
    { name: 'Hugging Face · MLX', url: `${HF}?pipeline_tag=text-generation&library=mlx&sort=trending`,
      note: 'Fastest on Apple silicon' },
    { name: 'LM Studio', url: 'https://lmstudio.ai/models', note: 'Curated, by size' },
    { name: 'ModelScope', url: 'https://modelscope.cn/models', note: 'Mirror of most releases' },
  ],
  image: [
    { name: 'Hugging Face', url: `${HF}?pipeline_tag=text-to-image&sort=trending`, note: 'Official releases' },
    { name: 'Civitai', url: 'https://civitai.com/models', note: 'Fine-tunes and LoRAs' },
    { name: 'ModelScope', url: 'https://modelscope.cn/models', note: 'Mirror of most releases' },
  ],
  video: [
    { name: 'Hugging Face', url: `${HF}?pipeline_tag=text-to-video&sort=trending`, note: 'Official releases' },
    { name: 'Civitai', url: 'https://civitai.com/models', note: 'Fine-tunes and LoRAs' },
    { name: 'ModelScope', url: 'https://modelscope.cn/models', note: 'Mirror of most releases' },
  ],
  'voice-stt': [
    { name: 'Hugging Face', url: `${HF}?pipeline_tag=automatic-speech-recognition&sort=trending`,
      note: 'Whisper and others' },
    { name: 'ModelScope', url: 'https://modelscope.cn/models', note: 'Mirror of most releases' },
  ],
  'voice-tts': [
    { name: 'Hugging Face', url: `${HF}?pipeline_tag=text-to-speech&sort=trending`, note: 'Voices and engines' },
    { name: 'ModelScope', url: 'https://modelscope.cn/models', note: 'Mirror of most releases' },
  ],
};

function hubsFor(category: string): Hub[] {
  return HUBS[category] ?? HUBS.text;
}

export default function ModelHubs({ category, onAdd }: { category: string; onAdd: () => void }) {
  return (
    <section className="card p-4 mb-8">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <h2 className="text-sm">Find more models</h2>
        <span className="text-[11px] text-[var(--text-faint)]">Opens in your browser</span>
      </div>
      <p className="text-[11px] text-[var(--text-faint)] mt-1 mb-3 max-w-xl leading-relaxed">
        The list below is checked: licence read, files confirmed to load. For anything else,
        go straight to where it is published — the publisher's own terms and gates apply there.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {hubsFor(category).map((hub) => (
          <button
            key={hub.name}
            type="button"
            onClick={() => { void openExternal(hub.url); }}
            className="flex items-center justify-between gap-3 text-left px-3 py-2.5 rounded-lg bg-[var(--bg-inset)] hover:bg-[var(--surface-hover)] transition group"
          >
            <span className="min-w-0">
              <span className="block text-xs">{hub.name}</span>
              <span className="block text-[10px] text-[var(--text-faint)]">{hub.note}</span>
            </span>
            <ArrowUpRight size={14} className="text-[var(--text-faint)] group-hover:text-[var(--text)] shrink-0" />
          </button>
        ))}
      </div>
      <button
        type="button"
        onClick={onAdd}
        className="mt-3 flex items-center gap-1.5 text-[11px] text-[var(--text-dim)] hover:text-[var(--text)] transition"
      >
        <FolderPlus size={13} /> Downloaded something? Add a model you have
      </button>
    </section>
  );
}
