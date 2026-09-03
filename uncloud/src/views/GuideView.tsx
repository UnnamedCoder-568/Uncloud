import {
  MessageSquare, Boxes, Workflow, ImageIcon, Music, Mic, Settings as Cog,
} from 'lucide-react';
import { useSettings } from '../lib/useSettings';

interface Section {
  id: string;
  icon: React.ComponentType<{ size?: number; strokeWidth?: number }>;
  title: string;
  lead: string;
  points: { term: string; body: string }[];
}

const SECTIONS: Section[] = [
  {
    id: 'models', icon: Boxes, title: 'Models', lead:
      'Everything starts here. Uncloud runs models you have downloaded — nothing is streamed from a server.',
    points: [
      { term: 'Browse and download', body: 'Pick from the catalog and it downloads into your models folder. Transfers resume if interrupted.' },
      { term: 'Bring your own', body: 'Point Uncloud at a folder that already holds .gguf or diffusers models and they appear automatically.' },
      { term: 'Size matters', body: 'On 24 GB, plan for one large model at a time. Uncloud unloads the chat model before image, music or narration work, because they cannot share memory.' },
    ],
  },
  {
    id: 'chat', icon: MessageSquare, title: 'Chat', lead:
      'A conversation with a model running on your machine.',
    points: [
      { term: 'Pick a model first', body: 'The selector at the top loads it into memory. Large models take a minute on first load.' },
      { term: 'Talk to it', body: 'If a speech-to-text model is installed, the mic button records and transcribes. The speaker icon reads replies aloud.' },
      { term: 'Vision', body: 'Models such as Gemma 4 and Qwen3.8 can look at images as well as read text.' },
      { term: 'Pictures in the reply', body: 'A model can show a quick sketch alongside its answer when one would help. These are deliberately rough \u2014 six steps at 512px, made to think with. Use the Image tab for anything you intend to keep.' },
    ],
  },
  {
    id: 'image', icon: ImageIcon, title: 'Image', lead:
      'Four related tools, each with a different job.',
    points: [
      { term: 'Generate', body: 'Text to image. Options on the right control steps, guidance, size and seed — reuse a seed to get the same picture twice.' },
      { term: 'Product', body: 'Give it one clean photo of a real product and it re-photographs it: on a model, as a flat lay, as a detail shot. Output quality tracks the input photo closely, so use the sharpest one you have.' },
      { term: 'Edit', body: 'Describe a change to an existing image — swap the background, add text, recolour a garment. Say what should stay the same as well as what should change.' },
      { term: 'Outputs', body: 'Everything generated appears in the Outputs tab, wherever you pointed the output folder in Settings. Reveal opens it in Finder.' },
      { term: 'Characters', body: 'Save a person once and reuse them. Traits carry everywhere; a reference image carries identity far more strongly, but only in Generate and Edit, since Product needs that slot for your product.' },
    ],
  },
  {
    id: 'music', icon: Music, title: 'Music', lead:
      'Instrumental beds or full songs with vocals, exported ready for a DAW.',
    points: [
      { term: 'Two modes', body: 'Instrumental, or with vocals from lyrics you write. Use [verse] and [chorus] markers to shape the arrangement.' },
      { term: 'Stems', body: 'Tick the box and you also get drums, bass, vocals and other as separate files — mixable in Logic rather than one frozen stereo bounce.' },
      { term: 'Format', body: 'WAV or AIFF, 44.1/48/96 kHz, 16/24/32-bit. Logic reads both natively. It cannot read FLAC, which is why that is not offered.' },
    ],
  },
  {
    id: 'voice', icon: Mic, title: 'Voice', lead:
      'Long-form narration, plus transcription and short clips.',
    points: [
      { term: 'One pass, not stitched', body: 'A 45-minute script is generated in a single pass, so the voice stays consistent throughout. Chunked tools drift in tone and leave audible joins.' },
      { term: 'Two engines', body: 'Realtime is faster than real time but slightly compressed. Quality sounds fuller and takes longer. Voices differ between them.' },
      { term: 'Quality setting', body: 'Controls diffusion steps. Higher is clearer and slower — worth raising for anything you intend to publish.' },
    ],
  },
  {
    id: 'agent', icon: Workflow, title: 'Agent', lead:
      'Give it a goal; it plans the steps and carries them out with real tools.',
    points: [
      { term: 'What it can reach', body: 'Files, a shell, web search and reading, a real browser it can click and type in, image generation, and vision when a suitable model is loaded.' },
      { term: 'It remembers', body: 'The plan is written to disk as it runs, so progress survives a restart and you can see exactly which step failed.' },
      { term: 'Scope', body: 'By default it is confined to its own workspace folder. Full device access is a deliberate switch in Settings.' },
      { term: 'Match the model', body: 'Planning quality depends heavily on the model. Small models plan poorly on multi-step work; a 27B handles it far better.' },
      { term: 'Tool sets', body: 'Every tool it can see costs room in the planner\u2019s prompt, so the set is matched to the model: a small one gets 13 tools, a large one all 34. Settings lets you override that per group.' },
      { term: 'Its own pointer', body: 'It can click at coordinates and drag inside its browser using a pointer of its own. That pointer is not your mouse \u2014 you can keep working while it does.' },
      { term: 'Skills', body: 'Written procedures it can look up. Drop a folder in ~/.uncloud/skills with a SKILL.md inside, or just ask the agent to remember how something is done and it writes one. Skills are instructions, never code.' },
    ],
  },
  {
    id: 'settings', icon: Cog, title: 'Settings', lead: 'Where the app is configured.',
    points: [
      { term: 'Models folder', body: 'Change it any time. Uncloud rescans and picks up whatever is there.' },
      { term: 'Hugging Face token', body: 'Optional. Speeds up downloads and unlocks gated models such as FLUX.2.' },
      { term: 'Agent device access', body: 'Off by default. Turning it on lets the agent run shell commands anywhere on your machine.' },
      { term: 'Agent tools', body: 'Which groups of tools the agent can see. Left automatic it follows the loaded model\u2019s size, which is usually what you want.' },
      { term: 'Keep this machine awake', body: 'Stops the machine sleeping while a job runs. Worth turning on before a long narration \u2014 otherwise the display times out and the job is suspended half-finished.' },
    ],
  },
];

export default function GuideView() {
  const modelsDir = useSettings()?.models_dir ?? '';

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-2xl mx-auto px-8 py-10">
        <h1 className="text-2xl font-semibold">Getting around Uncloud</h1>
        <p className="mt-2 text-sm text-[var(--text-dim)] leading-relaxed">
          Every model runs on this machine. Once the files are downloaded, none of it
          needs an internet connection.
        </p>

        <div className="mt-8 card p-4">
          <h2 className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">
            If you're starting fresh
          </h2>
          <ol className="mt-3 flex flex-col gap-2 text-sm text-[var(--text-dim)] list-decimal list-inside">
            <li>Open <strong className="text-[var(--text)]">Models</strong> and download a chat model.</li>
            <li>Open <strong className="text-[var(--text)]">Chat</strong>, select it, and say hello.</li>
            <li>Add an image or voice model when you need one.</li>
          </ol>
          {modelsDir && (
            <p className="mt-3 text-[11px] text-[var(--text-faint)]">
              Models folder: <span className="font-mono">{modelsDir}</span>
            </p>
          )}
        </div>

        <div className="mt-8 flex flex-col gap-8">
          {SECTIONS.map(({ id, icon: Icon, title, lead, points }) => (
            <section key={id}>
              <div className="flex items-center gap-2.5">
                <Icon size={16} strokeWidth={1.75} />
                <h2 className="text-base font-semibold">{title}</h2>
              </div>
              <p className="mt-1.5 text-sm text-[var(--text-dim)]">{lead}</p>
              <dl className="mt-3 flex flex-col gap-2.5 border-l border-[var(--border)] pl-4">
                {points.map((p) => (
                  <div key={p.term}>
                    <dt className="text-xs font-medium">{p.term}</dt>
                    <dd className="text-xs text-[var(--text-dim)] leading-relaxed mt-0.5">{p.body}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
        </div>

        <section className="mt-10 pt-6 border-t border-[var(--border)]">
          <h2 className="text-base font-semibold">Where your files go</h2>
          <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-5 gap-y-1.5 text-xs">
            {[
              ['Generated output', '~/.uncloud/outputs/'],
              ['Saved characters', '~/.uncloud/characters/'],
              ['Saved voices', '~/.uncloud/voices/'],
              ['Agent workspace', '~/.uncloud/workspace/'],
              ['Skills', '~/.uncloud/skills/'],
              ['Settings', '~/.uncloud/settings.json'],
            ].map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-[var(--text-dim)]">{k}</dt>
                <dd className="font-mono text-[var(--text-faint)]">{v}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="mt-8 pt-6 border-t border-[var(--border)]">
          <h2 className="text-base font-semibold">When something misbehaves</h2>
          <dl className="mt-3 flex flex-col gap-2.5 text-xs">
            {[
              ['Everything slows to a crawl', 'You have exceeded physical memory and the machine is swapping. Close other apps, or pick a smaller model — this degrades sharply rather than gradually.'],
              ['A model is missing from a picker', 'Each tab only lists models it can actually use. Reference editing needs Kontext; narration needs VibeVoice.'],
              ['First generation takes minutes', 'Loading multi-gigabyte weights, most of it disk read. Later runs on the same model are much quicker.'],
              ['The agent did something odd', 'Check its plan — each step records what happened, including why one failed.'],
            ].map(([k, v]) => (
              <div key={k}>
                <dt className="font-medium">{k}</dt>
                <dd className="text-[var(--text-dim)] leading-relaxed mt-0.5">{v}</dd>
              </div>
            ))}
          </dl>
        </section>
      </div>
    </div>
  );
}
