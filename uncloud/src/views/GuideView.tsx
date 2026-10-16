import {
  MessageSquare, Boxes, Workflow, ImageIcon, Music, Mic, Clock, Clapperboard, Drama, FolderOpen, Settings as Cog,
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
      {"term": "Transfers", "body": "Progress and downloaded size cover the whole model, including all weight files. The active filename shows which part is transferring. Pause and resume preserve completed files and supported partial transfers. A model becomes available only after every required file finishes. A failed transfer shows a reason; it is not marked complete."},
      {"term": "Remove a model", "body": "Remove from Library hides the entry without deleting its files. The file-deletion option removes data from the device and requires explicit approval."},
      {"term": "Memory", "body": "Model size, context length and other active engines all use memory. If work is slow, check Models in memory in Settings; avoid loading more than the machine can hold."},
    ],
  },
  {
    id: "chat", icon: MessageSquare, title: "Chat",
    lead: "Conversation with the selected model using its native template. No app identity is added. With Web and Pictures off, typed Chat adds no built-in system message.",
    points: [
      {"term": "Model and settings", "body": "Choose a model beside the message field. Model controls show the thinking settings actually declared by its native template. A binary model shows Auto / Off / On; graded effort appears only for models that support it. Auto leaves thinking to the model. Uncloud does not classify your message, change effort for greetings, or assign a fraction of your reply to thinking. A separate thinking token limit is available only when the native backend supports it and you explicitly set one. Manual overrides follow model switches until reset; unsupported controls are reported. Voice manner applies only to spoken replies. Typed Chat adds no built-in system prompt when Web and Pictures are off."},
      {"term": "History", "body": "Saved conversations in the Chat header opens a temporary left panel. Choose a conversation, click outside or press Escape to close it. Navigation stays separate."},
      {"term": "Reply actions", "body": "Hover over your message to copy its original text, or an answer to reveal Copy, Note and Chisel. The messages stay in place when the controls appear. Keyboard focus also reveals them; on touch screens they stay visible. Chisel hands the conversation to the tool-enabled workspace, where file changes still follow its access and approval settings."},
      {"term": "Dynamic context and Compact", "body": "The counter measures the current working context with the model’s native template, including tools and retained evidence. Near 75%, Chat automatically summarizes older exchanges while keeping recent messages. Every original message stays in the encrypted conversation. Compatible models can search older messages locally through conversation_search, even with Web off. Other backends receive locally matched excerpts when relevant. No extra model is loaded for retrieval, and it cannot search another conversation. If a summary fails, Chat uses a measured recent window and explains that older messages remain saved for recall. Inspect Compacted memory to see the summary. Manual Compact is still available. Compaction has a 90-second deadline, can be stopped, and detects sustained exact thinking cycles. Empty, cut-off or non-shrinking summaries are not applied. Summaries can omit details and search depends on relevance; neither guarantees perfect recall or expands the model’s native limit. A single oversized latest input or retained memory can still need a larger window or a smaller input. GGUF context Apply reloads the model and shows its actual allocated window and declared maximum. Leave the field blank and Apply for Auto, which lets compatible native runtimes fit the model and attention cache to available memory. Custom values are saved per model and cannot exceed its supported window. Larger windows use more memory."},
      {"term": "Model activity", "body": "The small animation indicates loading, waiting/generation or compaction. Reasoning may precede answer text. Stop cancels the response; failures should show an explanation."},
      {"term": "Web and images", "body": "With Web on and a compatible native tool-calling model/backend, the model can request a search or source page for any topic. Tool definitions use the model’s own chat template; Chat does not add a date, persona or written web instructions. The Tools.jinja registry contains only function names, descriptions and parameter schemas. Result labels are neutral and contain no response instructions; original source names and URLs are retained. Unsupported runtimes show this in the Web control; a supplied page URL can still be read. A keyword or product-name classifier does not decide whether it may search. Availability does not force a lookup: direct answers need no network request. Follow-ups such as ‘look it up’ use the actual conversation. Ask to read a supplied page URL to bypass search. Sources remain with the saved conversation and are counted in its context. Duplicate requests are not searched repeatedly. Web off and developer raw mode block these lookups; internet permission in Settings still applies. Search currently uses DuckDuckGo Lite and Bing RSS. Providers or destination pages can be unavailable. Pictures adds image instructions only when you request an image. Thinking text never executes a tool. Image attachments require a compatible vision model and runtime."},
      {"term": "Automatic sampling", "body": "Model generation metadata and your saved overrides take priority. A verified profile can supply the publisher’s sampling recommendations when the download omits them; unspecified controls remain native. No temperature multiplier or application-defined creativity preset is applied. MLX Auto output can use the remaining selected context window instead of the library’s generic 512-token ceiling; the model still stops naturally. A manual reply limit remains a ceiling, includes thinking, and is never raised. The actual remaining context can bound a request without changing your saved value. Web evidence fitting no longer caps an Auto reply to its fitting reserve. Native GGUF generation stops at the loaded context boundary instead of silently shifting the conversation and continuing indefinitely. Sustained exact thinking cycles are stopped with a visible error; Auto thinking and the model’s samplers stay unchanged. Inspect Advanced and effective configuration for sources and overrides. Clear an override to return that field to Auto."},
      {"term": "Dictation and Talk", "body": "Dictation transcribes into the message field. Talk listens and answers aloud. Enable Speak in Chat settings to hear replies without hands-free listening."},
    ],
  },
  {
    id: "personas", icon: Drama, title: "Personas",
    lead: "User-written roles and personalities, selected before starting a model conversation.",
    points: [
      {"term": "Create and edit", "body": "Add a name, write the exact instructions you want, and choose an installed model. Save keeps the profile without loading any weights. Start conversation loads or reuses that model. Edit a saved persona to change future conversations."},
      {"term": "Scope and history", "body": "Persona instructions apply only in Personas. Chat, Chisel and Jarviz do not inherit them. Profiles and conversations are encrypted locally and separated by paired device. Saved conversations retain their original persona instructions; a new conversation uses the latest saved profile."},
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
    id: "jarviz", icon: Mic, title: "Jarviz",
    lead: "Talk, text to voice, voice conversion, transcription and saved clips in one workspace.",
    points: [
      {"term": "Talk", "body": "Choose a local text model and reply voice, then press Talk. Jarviz streams the model’s own response without adding an assistant identity or personality instruction. Leaving the Talk tab stops listening. Use Personas to explicitly choose a personality, and Chisel for computer actions."},
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
      {"term": "Progress", "body": "Inspect the plan, individual tool results and errors. Start with a small disposable task, then increase complexity. Stored progress is inspectable in the notification inbox. A restart invalidates unanswered approvals. Resume remaining work retains completed steps and asks again where needed; an action interrupted mid-execution requires review and is not repeated automatically. Chisel’s context counter includes the tool contract and handoff."},
    ],
  },
  {
    id: "automations", icon: Clock, title: "Automations",
    lead: "Scheduled agents are separate from interactive Chisel.",
    points: [
      {"term": "Recipes", "body": "Open the Recipes tab to save reusable action steps, declare inputs and run them again. Agents & schedules holds model-driven tasks and their schedules. Both use your existing connections and permissions. Existing saved recipes and schedules are retained."},
      {"term": "Schedule", "body": "Choose a model, goal, first-run time and one-off/hourly/daily/weekly schedule. Uncloud must stay open. Missed runs are not replayed in a burst."},
      {"term": "Control", "body": "Pause/resume or review recent runs. Only one scheduled agent runs at a time. Interrupted runs pause for review; unattended access is limited to workspace reads and permitted research."},
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
      {"term": "Models and permissions", "body": "Choose models/output folders, inspect resident models and converted caches, and manage tool permissions and activity history. Models in memory lists current text, image, video, cached transcription, voice and narration models, plus active worker/job counts. A text-model switch waits for the old process to exit before loading its replacement. Unload all also clears cached voice and narration models. The text row shows the runtime’s detected GPU availability and allocated context; GPU availability does not measure layer offloading or utilization. Windows includes a Vulkan GPU runtime and uses it when a usable GPU is detected, with a CPU fallback. Graphics drivers must support Vulkan. Clearing history does not grant access."},
      {"term": "Connections", "body": "Configure supported integrations, inference providers and MCP tools. A Hugging Face token can help with access/rate limits; gated models still require the publisher’s authorization."},
      {"term": "Updates", "body": "Automatic checking shows a top banner and inbox event when a signed app update is available. Check now in Updates for a manual check. Offline failures can be retried; installation restarts the app."},
      {"term": "Notifications and background tasks", "body": "The header bell keeps permission requests, questions, failures and completions. Open a system alert to review the matching item; clicking never approves an action. Allow or Deny inside the inbox. Settings → Notifications controls categories, silence, system permission and a test alert. Native previews hide private content. Focus and OS settings can suppress delivery. Keep running in background makes window close hide Uncloud; otherwise close quits. The tray/menu bar can reopen, stop tasks or quit. Notification history and task recovery are encrypted using the conversation vault; fallback key storage has the same limits as conversation encryption."},
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
