import {
  MessageSquare, Boxes, Workflow, ImageIcon, Music, Mic, Clock, Clapperboard, ChefHat, FolderOpen, Settings as Cog,
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
    id: "models", icon: Boxes, title: "Models",
    lead: "Add only the models and runtimes you need.",
    points: [
      {"term": "Download or import", "body": "Browse the catalog, or use Add from disk on the computer running Uncloud. Model availability depends on platform, file format and installed engine."},
      {"term": "Transfers", "body": "Use the download controls to pause, resume or cancel. Resuming reuses supported partial downloads; a failed transfer should show a reason."},
      {"term": "Remove a model", "body": "Remove from Library hides the entry without deleting its files. The file-deletion option removes data from the device and requires explicit approval."},
      {"term": "Memory", "body": "Model size, context length and other active engines all use memory. If work is slow, check Models in memory in Settings; avoid loading more than the machine can hold."},
    ],
  },
  {
    id: "chat", icon: MessageSquare, title: "Chat",
    lead: "Direct conversation with the selected model.",
    points: [
      {"term": "Model and settings", "body": "Choose a model beside the message field. Chat settings contains model temperature, reply budget, attachments, Web, Pictures and Speak. Auto uses the model/runtime profile; explicit overrides remain your choice."},
      {"term": "History", "body": "Saved conversations in the Chat header opens a temporary left panel. Choose a conversation, click outside or press Escape to close it. Navigation stays separate."},
      {"term": "Context and Compact", "body": "The counter below the composer uses the selected model’s effective context window. Near 75%, Compact preserves structured memory and recent turns. Inspect Compacted memory to see what is retained."},
      {"term": "Model activity", "body": "The small animation indicates loading, waiting/generation or compaction. Reasoning may precede answer text. Stop cancels the response; failures should show an explanation."},
      {"term": "Web and images", "body": "Enable Web for online sources and Pictures for generated images. Image attachments require a compatible vision model. These capabilities need their appropriate runtime and permissions."},
      {"term": "Dictation and Talk", "body": "Dictation transcribes into the message field. Talk listens and answers aloud. Enable Speak in Chat settings to hear replies without hands-free listening."},
    ],
  },
  {
    id: "friday", icon: Mic, title: "Friday",
    lead: "A local voice companion with a calm, concise personality.",
    points: [
      {"term": "Begin", "body": "Choose a local text model and reply voice, then press Talk. Emma is the starting voice; you can select another preset or saved voice."},
      {"term": "Stop and retry", "body": "Stop ends listening and cancels pending inference. Microphone or speech errors appear in the view. Retry after correcting missing models or permissions."},
      {"term": "Capabilities", "body": "Friday’s current section is for conversation. Use Chisel for tool execution and computer actions. Friday is an original assistant, not a reproduction of an actor or fictional character."},
    ],
  },
  {
    id: "image", icon: ImageIcon, title: "Image",
    lead: "Generate, Product, Edit and Characters share your local image engines.",
    points: [
      {"term": "Automatic model settings", "body": "Steps, guidance and supported dimensions come from model metadata/profile and runtime recommendations where available. Switching models applies that model’s recommendations. Save defaults only for your preferred override; Reset restores recommendations."},
      {"term": "LoRA", "body": "In Generate → Options, choose a compatible .safetensors LoRA and its strength. An adapter must match the base model and supported backend. Remove adapter returns to base generation."},
      {"term": "Reference and editing", "body": "Product uses a product reference; Edit changes an existing image. Choose a compatible editing model and describe what must remain unchanged. Characters can retain traits and references where supported."},
      {"term": "Seeds and jobs", "body": "Keep the same seed, model and settings when comparing results. Reproducibility can differ between engines or versions. Stop cancels work; batch entries retain their seeds and progress."},
    ],
  },
  {
    id: "video", icon: Clapperboard, title: "Video",
    lead: "Create a clip with an installed compatible video model.",
    points: [
      {"term": "Settings", "body": "Choose the model, duration, size, steps and guidance. Recommendations and memory checks depend on the model/backend; longer or larger clips need more resources."},
      {"term": "Progress", "body": "Generation may load weights before frame processing begins. Stop unwanted work. Outputs keeps completed clips; missing engines or incompatible models should be reported."},
    ],
  },
  {
    id: "music", icon: Music, title: "Music",
    lead: "Instrumental or vocal generation with installed music engines.",
    points: [
      {"term": "Compose", "body": "Describe a style, choose instrumental or vocals, then set length and available tempo/key controls. Vocal mode uses your lyrics."},
      {"term": "Stems and export", "body": "Split into stems requires the separation runtime. Choose output rate and bit depth for your workflow. Generated tracks and stems appear in Outputs."},
    ],
  },
  {
    id: "voice", icon: Mic, title: "Voice",
    lead: "Text to voice, voice conversation, transcription and saved clips.",
    points: [
      {"term": "Choose an engine", "body": "Text to voice offers Kokoro, Apple Silicon Kokoro where supported, Chatterbox, Bark and VibeVoice. Each needs its own installed runtime and weights. First use can take longer than warm synthesis."},
      {"term": "Recordings and voices", "body": "Transcribe converts speech to text. Voice to voice can converse or convert a recording with a compatible Chatterbox model. Only use voices you own or have permission to use."},
      {"term": "Narration and clips", "body": "Long-form narration exposes its engine-specific controls. Script length and memory affect generation. Clips lets you revisit completed speech and export it."},
    ],
  },
  {
    id: "training", icon: Boxes, title: "Train",
    lead: "Models \u2192 Train creates adapters from your examples.",
    points: [
      {"term": "Text adapters", "body": "Choose a compatible base model, name and JSONL dataset. One JSON object per line contains messages or a prompt/completion pair. Review dataset and memory checks before starting."},
      {"term": "Settings and export", "body": "Start with a preset or customize steps, batch size, learning rate, rank, layers and example length. Follow Runs and cancel if needed. A text adapter needs its original base; the export control can merge it into a quantized copy where supported."},
      {"term": "Image LoRA", "body": "The Image LoRA tab uses local images and matching caption .txt files. Current training requires Apple Silicon and MFlux, local weights and compatible training configuration. Check dataset and model before starting."},
      {"term": "Online teachers", "body": "An inference API generates answers; it does not automatically train a local model. Provider-assisted dataset preparation and local adapter training are separate steps. Do not assume every provider or model family supports training."},
    ],
  },
  {
    id: "quantize", icon: Boxes, title: "Quantize",
    lead: "Models \u2192 Quantize creates a smaller copy of a supported model.",
    points: [
      {"term": "Choose a supported source", "body": "Review available base/model choices and output precision. Quantization reduces storage and memory, with possible quality loss; supported conversions depend on backend and architecture."},
      {"term": "Keep the source", "body": "Use a new output name and keep the original until you compare quality. Follow progress and Stop if needed. Exported text adapters can be followed here too."},
    ],
  },
  {
    id: "chisel", icon: Workflow, title: "Chisel",
    lead: "Plan and execute tasks using tools activated for the goal.",
    points: [
      {"term": "Scope and approvals", "body": "Workspace file access is constrained by default. Full device access is a deliberate Settings choice; shell and desktop actions still follow approvals and OS permissions. Review the action before allowing it."},
      {"term": "Tools and skills", "body": "Choose tool groups in Settings or use automatic selection. Skills are written procedures; connected tools/providers need configuration. More tools do not guarantee better planning."},
      {"term": "Computer and browser", "body": "Browser automation operates inside its browser. Desktop control interacts with your actual desktop and requires appropriate OS permission. Live previews depend on an active, permitted session."},
      {"term": "Progress", "body": "Inspect the plan, individual tool results and errors. Start with a small disposable task, then increase complexity. Stored progress is inspectable; a restart is not a promise that a task automatically continues."},
    ],
  },
  {
    id: "automations", icon: Clock, title: "Automations",
    lead: "Scheduled agents are separate from interactive Chisel.",
    points: [
      {"term": "Schedule", "body": "Choose a model, goal, first-run time and one-off/hourly/daily/weekly schedule. Uncloud must stay open. Missed runs are not replayed in a burst."},
      {"term": "Control", "body": "Pause/resume or review recent runs. Only one scheduled agent runs at a time. Interrupted runs pause for review; unattended access is limited to workspace reads and permitted research."},
    ],
  },
  {
    id: "recipes", icon: ChefHat, title: "Recipes",
    lead: "Reusable workflows, separate from model training.",
    points: [
      {"term": "Build and run", "body": "Create a recipe, add parameters and supported action steps, then run it with those inputs. Each action uses current connections, permissions and approvals. A failed step should be visible."},
    ],
  },
  {
    id: "outputs", icon: FolderOpen, title: "Outputs",
    lead: "Find and export completed images, clips, tracks and speech.",
    points: [
      {"term": "Browse", "body": "Filter by media type or Refresh. Settings controls the output directory. Reveal opens the system file browser on supported desktop platforms."},
      {"term": "Manage", "body": "Save a copy before deleting anything you need. Output deletion and model file deletion are separate operations."},
    ],
  },
  {
    id: "settings", icon: Cog, title: "Settings",
    lead: "Preferences, connections, permissions and diagnostics.",
    points: [
      {"term": "General", "body": "Appearance, printer sound, keep-awake protection, terms and version information. Keep awake prevents system sleep while enabled and Uncloud is open; the display may still turn off."},
      {"term": "Models and permissions", "body": "Choose models/output folders, inspect resident models and converted caches, and manage tool permissions and activity history. Clearing history does not grant access."},
      {"term": "Connections", "body": "Configure supported integrations, inference providers and MCP tools. A Hugging Face token can help with access/rate limits; gated models still require the publisher’s authorization."},
      {"term": "Updates", "body": "Automatic checking shows a top notification when a signed app update is available. Check now in Updates for a manual check. Offline failures can be retried; installation restarts the app."},
      {"term": "Developer", "body": "Inference diagnostics and direct/raw mode help distinguish model/backend behavior from context and tools. These are troubleshooting controls, not guaranteed speed improvements."},
    ],
  },
];

export default function GuideView() {
  const settings = useSettings();
  const modelsDir = settings?.models_dir ?? '';

  return (
    <div className="h-full overflow-y-auto">
      <div className="page-column">
        <h1 className="text-2xl font-semibold">Getting around Uncloud</h1>
        <p className="mt-2 text-sm text-[var(--text-dim)] leading-relaxed">
          Local models run on this machine after download. Web searches, model downloads
          and connected online providers need an internet connection.
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

        <nav aria-label="Guide topics" className="mt-6 flex flex-wrap gap-2">{SECTIONS.map(section => <a className="pill text-xs" href={`#guide-${section.id}`} key={section.id}>{section.title}</a>)}</nav>
        <div className="mt-8 flex flex-col gap-8">
          {SECTIONS.map(({ id, icon: Icon, title, lead, points }) => (
            <section key={id} id={`guide-${id}`}>
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
              ['Generated output', settings?.output_dir || '~/.uncloud/outputs/'],
              ['Saved characters', '~/.uncloud/characters/'],
              ['Saved voices', '~/.uncloud/voices/'],
              ['Chisel workspace', '~/.uncloud/workspace/'],
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
              ['Everything slows to a crawl', 'Memory pressure can cause swapping and severe slowdown. Check resident models and running jobs; close unused work or try a smaller model.'],
              ['A model is missing from a picker', 'Each tab lists compatible models. Check its category, metadata, local files and required runtime; editing and narration have additional requirements.'],
              ['First generation takes minutes', 'First use may load weights and initialize the runtime. Inspect progress and errors; a continuing spinner without progress should not be treated as success.'],
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
