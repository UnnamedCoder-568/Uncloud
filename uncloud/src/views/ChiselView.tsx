import { useCallback, useEffect, useRef, useState } from 'react';
import { CheckCircle2, XCircle, Loader2, Circle, Send, ShieldAlert, Cpu, Square, MessagesSquare, AudioLines, Copy, NotebookPen, Check } from 'lucide-react';
import { agentSocket, cancelAgentRun, getLibrary, startEngine, engineStatus, saveNote } from '../lib/sidecar';
import type { LocalModel } from '../lib/sidecar';
import Dictate from '../components/Dictate';
import ReplyVoice from '../components/ReplyVoice';
import AddFromDisk from '../components/AddFromDisk';
import { onLibraryChange } from '../lib/library-changed';
import { describeTalk, useTalk } from '../lib/useTalk';
import { useSettings } from '../lib/useSettings';
import { onHandoffSignal, takeHandoff } from '../lib/handoff';
import { printerSound } from '../lib/printer-sound';
import Markdown from '../components/Markdown';
import ActivityOrb from '../components/ActivityOrb';

interface AgentTask {
  id: string;
  description: string;
  tool_id: string;
  args: Record<string, unknown>;
  dependencies: string[];
  status: 'pending' | 'in_progress' | 'completed' | 'failed';
  output: string | null;
  error: string | null;
}
interface AgentGraph {
  goal: string;
  tasks: Record<string, AgentTask>;
  start_node_ids: string[];
}

function taskOrbState(toolId: string) {
  if (toolId.startsWith('web_') || toolId.includes('search')) return 'searching' as const;
  if (toolId.includes('image') || toolId.includes('write') || toolId.includes('create')) return 'shaping' as const;
  if (toolId.includes('browser') || toolId.includes('connect')) return 'connecting' as const;
  return 'solving' as const;
}

function TaskOutput({ task }: { task: AgentTask }) {
  const [copied, setCopied] = useState(false);
  const [saved, setSaved] = useState(false);
  const output = task.output ?? '';
  if (!output) return null;
  const shown = output.length > 12_000
    ? `${output.slice(0, 12_000)}\n\n_(output clipped on screen)_` : output;
  return (
    <div className="mt-2 rounded-lg bg-[var(--bg-inset)] p-3 overflow-x-auto">
      <Markdown>{shown}</Markdown>
      <div className="mt-2 flex items-center gap-1 text-[10px] text-[var(--text-faint)]">
        <button className="pill h-7 px-2" onClick={async () => {
          await navigator.clipboard.writeText(output);
          setCopied(true); setTimeout(() => setCopied(false), 1400);
        }}>{copied ? <Check size={11} /> : <Copy size={11} />} {copied ? 'Copied' : 'Copy'}</button>
        <button className="pill h-7 px-2" onClick={async () => {
          await saveNote(`${task.description.slice(0, 72)} · ${new Date().toLocaleString()}`, output);
          setSaved(true); setTimeout(() => setSaved(false), 1800);
        }}>{saved ? <Check size={11} /> : <NotebookPen size={11} />} {saved ? 'Saved' : 'Note'}</button>
      </div>
    </div>
  );
}

/** What to say when a spoken goal finishes: how it went, and the result of
 *  the last step, briefly — the whole output is on the screen. */
function spokenOutcome(graph: AgentGraph): string {
  const tasks = Object.values(graph.tasks);
  if (!tasks.length) return 'I could not make a plan for that.';
  const failed = tasks.filter((t) => t.status === 'failed');
  const dependedOn = new Set(tasks.flatMap((t) => t.dependencies));
  const last = [...tasks].reverse().find((t) => !dependedOn.has(t.id) && t.output);
  const plain = (text: string) => text.replace(/[#*_`>|[\]]/g, ' ').replace(/\s+/g, ' ').trim();
  const result = last?.output ? plain(last.output).slice(0, 400) : '';
  if (failed.length) {
    return `Done, but ${failed.length} of ${tasks.length} steps failed. ${plain(failed[0].error ?? '')}`.trim();
  }
  return result ? `Done. ${result}` : `Done. All ${tasks.length} steps finished.`;
}

export default function ChiselView() {
  const [goal, setGoal] = useState('');
  const [graph, setGraph] = useState<AgentGraph | null>(null);
  const [phase, setPhase] = useState<'idle' | 'planning' | 'running' | 'done' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);
  const settings = useSettings();
  const deviceAccess = settings?.agent_device_access ?? true;
  const wsRef = useRef<WebSocket | null>(null);
  const runIdRef = useRef<string | null>(null);
  const runEpoch = useRef(0);
  //: Whether the last close was asked for. A close the user requested
  //  must not be reported as the engine having died.
  const stopped = useRef(false);
  //: The conversation a handed-over goal came from, held in a ref rather than
  //  state: it is read once when the socket opens and never rendered, so
  //  putting it in state would only cost a re-render per handoff.
  const contextRef = useRef<{ role: string; content: string }[]>([]);
  const handoffModelRef = useRef<{ path: string; engine: string; name: string } | null>(null);
  const [handedOver, setHandedOver] = useState(0);

  // The agent plans with whichever text model the engine has loaded. That was
  // invisible here, so an unloaded engine looked like a broken agent.
  const [textModels, setTextModels] = useState<LocalModel[]>([]);
  const [loaded, setLoaded] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const readState = useCallback(async () => {
    const [ms, st] = await Promise.all([
      getLibrary().catch(() => [] as LocalModel[]),
      engineStatus().catch(() => null),
    ]);
    setTextModels(ms.filter((m) => m.category === 'text' && m.ready));
    setLoaded(st?.running ? st.model_path ?? null : null);
  }, []);

  useEffect(() => { readState(); }, [readState]);
  // A printer must not outlive the view it was describing.
  useEffect(() => () => printerSound.stop(), []);
  useEffect(() => onLibraryChange(() => { void readState(); }), [readState]);

  async function loadModel(m: LocalModel) {
    setLoading(true);
    try {
      await startEngine(m.path, m.engine);
      await readState();
    } finally {
      setLoading(false);
    }
  }

  //: Settled when a run ends, with what to say about it. Only a spoken goal
  //  waits on this; typing a goal never does.
  const settle = useRef<((spoken: string) => void) | null>(null);
  function finish(spoken: string) {
    settle.current?.(spoken);
    settle.current = null;
  }

  const [voice, setVoice] = useState(() => {
    try { return localStorage.getItem('uncloud.chisel.voice') || 'bm_george'; } catch { return 'bm_george'; }
  });
  useEffect(() => {
    try { localStorage.setItem('uncloud.chisel.voice', voice); } catch { /* storage refused */ }
  }, [voice]);

  /** Talk to Chisel: a spoken goal is run, and the outcome is read back, then
   *  it listens for the next one. */
  const talk = useTalk(voice, (said) => new Promise<string>((resolve) => {
    setGoal(said);
    settle.current = resolve;
    void run(said);
  }));

  //: How much of the agent's output has been seen. Chisel is handed whole
  //  graphs rather than a stream of words, so "the model is writing" is the
  //  total getting longer — and a step that runs a command in silence should
  //  not sound like one that is typing.
  const written = useRef(0);

  function clatter(graph: AgentGraph) {
    const total = Object.values(graph.tasks ?? {})
      .reduce((n, task) => n + (task.output?.length ?? 0), 0);
    if (total <= written.current) return;
    written.current = total;
    printerSound.writing();
  }

  async function run(override?: string) {
    const target = (override ?? goal).trim();
    if (!target || phase === 'planning' || phase === 'running') {
      finish(target ? 'I am still working on the last goal.' : '');
      return;
    }
    setError(null);
    setGraph(null);
    stopped.current = false;
    written.current = 0;
    printerSound.prepare();   // while this is still the Run gesture
    setPhase('planning');
    const epoch = ++runEpoch.current;
    const runId = crypto.randomUUID().replaceAll('-', '');
    runIdRef.current = runId;
    try {
      const handedModel = handoffModelRef.current;
      if (handedModel) {
        const current = await engineStatus().catch(() => null);
        if (!current?.running || current.model_path !== handedModel.path) {
          await startEngine(handedModel.path, handedModel.engine);
          await readState();
        }
      }
    } catch (e) {
      const message = `Could not load the model from Chat: ${String(e).replace(/^Error:\s*/, '')}`;
      setError(message);
      setPhase('error');
      finish(message);
      return;
    }
    const ws = await agentSocket();
    wsRef.current = ws;
    // Any message means the socket worked, so anything onerror reports after
    // that is the close, not a failure to connect. Without this the generic
    // "connection lost" overwrites whatever the engine actually said — a failed
    // task, or "no text model is loaded".
    let spoke = false;
    ws.onopen = () => ws.send(JSON.stringify({
      run_id: runId,
      goal: target,
      // The conversation this was handed over from, when it was. Background
      // for the planner, so it does not plan from one sentence in isolation.
      context: contextRef.current,
    }));
    ws.onmessage = (ev) => {
      if (epoch !== runEpoch.current) return;
      spoke = true;
      const msg = JSON.parse(ev.data);
      if (msg.type === 'planning') setPhase('planning');
      if (msg.type === 'graph') {
        setGraph(msg.graph);
        clatter(msg.graph);
        setPhase('running');
      }
      if (msg.type === 'done') {
        setGraph(msg.graph);
        setPhase('done');
        printerSound.stop();
        finish(spokenOutcome(msg.graph));
      }
      if (msg.type === 'error') {
        setError(msg.message);
        setPhase('error');
        printerSound.stop();
        finish(`That did not work. ${msg.message}`);
      }
      if (msg.type === 'cancelled') {
        if (msg.graph) setGraph(msg.graph);
        setPhase('idle');
        printerSound.stop();
        finish('');
      }
    };
    ws.onerror = () => {
      if (epoch !== runEpoch.current) return;
      if (spoke) return;
      setError('Connection to Uncloud engine lost');
      setPhase('error');
      finish('I lost the connection to the engine.');
    };
    // A clean close fires onclose, NOT onerror. Without this the view sat in
    // "planning" for ever with no spinner and no message, because nothing
    // moved it out of that state — which is how a dropped socket became a
    // blank screen.
    ws.onclose = () => {
      if (epoch !== runEpoch.current) return;
      setPhase((current) => {
        if (current === 'planning' || current === 'running') {
          // A close the user asked for is not a fault, and must not be
          // reported as one.
          if (stopped.current) { finish(''); return 'idle'; }
          finish('The engine stopped before the plan finished.');
          setError('The engine stopped before the plan finished. '
                   + 'It may have run out of memory loading the planning model.');
          return 'error';
        }
        return current;
      });
    };
  }

  /** Stop the run.
   *
   *  A plan can take minutes, and a plan going the wrong way is obvious long
   *  before it finishes. Without this the only way out was to close the
   *  window, which loses the whole conversation with it.
   */
  function stop() {
    stopped.current = true;
    runEpoch.current += 1;
    if (runIdRef.current) void cancelAgentRun(runIdRef.current).catch(() => {});
    runIdRef.current = null;
    try { wsRef.current?.close(); } catch { /* already gone */ }
    wsRef.current = null;
    setPhase('idle');
    setError(null);
  }

  const busy = phase === 'planning' || phase === 'running';
  //: A conversation handed over from Chat. The goal goes in the field so it
  //  is visible and editable, the conversation rides along as background, and
  //  the work starts — the point of handing over is not to arrive at a filled
  //  form and have to press a button.
  useEffect(() => {
    const claim = () => {
      const handoff = takeHandoff();
      if (!handoff) return;
      setGoal(handoff.goal);
      contextRef.current = handoff.context;
      handoffModelRef.current = handoff.model ?? null;
      setHandedOver(handoff.context.length);
      void run(handoff.goal);
    };
    // On mount as well as on the signal: the first handoff is what CREATES
    // this view, so the signal fires before there is anything here to hear it.
    claim();
    return onHandoffSignal(claim);
    // run is redefined every render, and depending on it would resubscribe on
    // every keystroke; the subscription must outlive that.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const orderedTasks = graph ? Object.values(graph.tasks) : [];

  return (
    <div className="h-full flex flex-col">
      <header className="px-6 pt-5 pb-4 border-b border-[var(--border-soft)]">
        <h1 className="text-2xl font-semibold mb-1">Chisel</h1>
        <p className="text-xs text-[var(--text-faint)]">
          Give it a goal — it plans the work with your local model and carries it out with real tools. Hand a conversation over from Chat and it picks up where you left off.
        </p>
        {!deviceAccess && (
          <div className="flex items-center gap-1.5 text-[11px] text-amber-400/90 mt-2">
            <ShieldAlert size={12} /> Scoped to the Uncloud workspace folder. Enable full device access in Settings for unrestricted shell/filesystem.
          </div>
        )}

        {/* Which model does the planning. Previously invisible here, so an
            engine with nothing loaded looked like a broken agent. */}
        <div className="flex items-center gap-2 mt-3 text-[11px]">
          <Cpu size={12} className="text-[var(--text-faint)] shrink-0" />
          {loaded ? (
            <>
              <span className="text-[var(--text-faint)]">Planning with</span>
              <span className="font-mono text-[var(--text-dim)] truncate">
                {loaded.split('/').pop()}
              </span>
            </>
          ) : textModels.length ? (
            <>
              <span className="text-amber-400/90">No text model loaded — the agent needs one to plan.</span>
              <select
                className="bg-[var(--bg-inset)] text-[11px] px-2 py-1 rounded-lg border border-[var(--border-soft)]"
                disabled={loading}
                defaultValue=""
                onChange={(e) => {
                  const m = textModels.find((x) => x.path === e.target.value);
                  if (m) loadModel(m);
                }}
              >
                <option value="">{loading ? 'Loading…' : 'Load one…'}</option>
                {textModels.map((m) => (
                  <option key={m.id} value={m.path}>{m.name} · {m.size_gb} GB</option>
                ))}
              </select>
              <AddFromDisk label="Add from disk…" className="flex items-center gap-1 text-[var(--text-faint)] hover:text-[var(--text-dim)]" />
            </>
          ) : (
            <>
              <span className="text-amber-400/90">
                No text models installed — download one from the Models tab, or
              </span>
              <AddFromDisk label="add one you already have" className="flex items-center gap-1 underline underline-offset-2 text-[var(--text-dim)] hover:text-white" />
            </>
          )}
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-5">
        {!graph && phase === 'idle' && (
          <div className="h-full flex items-center justify-center text-[var(--text-faint)] text-sm">
            No task graph yet. Describe a goal below.
          </div>
        )}
        {phase === 'planning' && (
          <div className="flex items-center gap-2 text-sm text-[var(--text-dim)]">
            <Loader2 size={14} className="animate-spin" /> Planning task graph…
          </div>
        )}
        {error && (
          <div className="flex items-center gap-2 text-sm text-rose-400 card p-3 border-rose-900/40">
            <XCircle size={14} /> {error}
          </div>
        )}

        {/* A plan with no steps rendered as an empty page: the model returned
            nothing usable and the interface said nothing at all. Whatever else
            is true, the user asked for something and deserves an answer. */}
        {graph && orderedTasks.length === 0 && phase !== 'planning' && (
          <div className="max-w-2xl card p-4 flex flex-col gap-2">
            <div className="flex items-center gap-2 text-sm text-amber-400">
              <XCircle size={14} /> No plan came back
            </div>
            <p className="text-xs text-[var(--text-dim)] leading-relaxed">
              The planning model did not produce any steps for this goal. That
              usually means the goal needs a tool Uncloud does not have, or the
              model is too small to plan it. Uncloud can search and read the
              web, read and write files, run shell commands and inspect a
              browser's console — it cannot drive another application's
              interface.
            </p>
            <p className="text-xs text-[var(--text-faint)]">
              Try a smaller, more concrete goal, or a larger planning model.
            </p>
          </div>
        )}

        {graph && orderedTasks.length > 0 && (
          <div className="max-w-2xl flex flex-col gap-3">
            {orderedTasks.map((task) => (
              <div key={task.id} className="card p-4 flex gap-3">
                <div className="pt-0.5">
                  {task.status === 'completed' && <CheckCircle2 size={16} className="text-emerald-400" />}
                  {task.status === 'failed' && <XCircle size={16} className="text-rose-400" />}
                  {task.status === 'in_progress' && (
                    <ActivityOrb state={taskOrbState(task.tool_id)} label={`Working on ${task.description}`} />
                  )}
                  {task.status === 'pending' && <Circle size={16} className="text-[var(--text-faint)]" />}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-sm">{task.description}</div>
                  <div className="text-[10px] font-mono text-[var(--text-faint)] mt-1 uppercase">{task.tool_id}</div>
                  <TaskOutput task={task} />
                  {task.error && <div className="text-[11px] text-rose-400 mt-2">{task.error}</div>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="p-4 border-t border-[var(--border-soft)]">
        {/* What came across from Chat. Silent context is untrustworthy
            context: the plan will read differently because of it, so the fact
            that it is there has to be visible, and droppable. */}
        {handedOver > 0 && (
          <div className="max-w-2xl mx-auto mb-2 flex items-center gap-2 text-[11px] text-[var(--text-faint)]">
            <MessagesSquare size={12} />
            <span>
              Carrying {handedOver} {handedOver === 1 ? 'message' : 'messages'} from Chat as background
            </span>
            <button
              className="underline underline-offset-2 hover:text-[var(--text-dim)]"
              onClick={() => { contextRef.current = []; setHandedOver(0); }}
            >
              drop
            </button>
          </div>
        )}
        {(talk.active || talk.error) && (
          <div className="max-w-2xl mx-auto mb-2 flex items-center gap-2 text-[11px] text-[var(--text-faint)] flex-wrap">
            <span>Answers in</span>
            <ReplyVoice value={voice} onChange={setVoice}
                        className="bg-[var(--bg-inset)] text-[11px] px-2 py-1 rounded-lg outline-none" />
            {talk.error && <span className="text-rose-400">{talk.error}</span>}
          </div>
        )}
        <div className="max-w-2xl mx-auto flex items-end gap-2 card px-3 py-2 focus-within:border-[#3a3a42]">
          <textarea
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                run();
              }
            }}
            placeholder="e.g. Summarize every .txt file in the workspace into notes.md"
            rows={1}
            className="flex-1 bg-transparent outline-none resize-none text-sm py-1.5 placeholder:text-[var(--text-faint)] max-h-40"
          />
          <Dictate
            title="Dictate the goal"
            onText={(t) => setGoal((v) => (v ? v.trimEnd() + ' ' + t : t))}
            className="mb-0.5"
          />
          {talk.ready && (
            <button
              onClick={talk.toggle}
              title={talk.active ? 'Stop talking' : 'Talk: say a goal, hear how it went, and carry on'}
              aria-label={talk.active ? 'Stop talking' : 'Talk'}
              className={`${talk.active ? 'pill pill-on' : 'pill'} mb-0.5 shrink-0`}
              style={talk.active ? { color: 'var(--accent)' } : undefined}
            >
              <AudioLines size={14} />
              <span>{talk.active ? describeTalk(talk.state) : 'Talk'}</span>
            </button>
          )}
          {/* One button, as in Chat: send while idle, stop while working. A
              separate stop button is dead weight for most of its life and is
              never where the hand already is. */}
          <button
            // Wrapped: passing `run` directly hands React's click event in as
            // the goal override, and the goal becomes a SyntheticEvent.
            onClick={() => (busy ? stop() : run())}
            disabled={!busy && !goal.trim()}
            title={busy ? 'Stop' : 'Start'}
            aria-label={busy ? 'Stop' : 'Start'}
            className="w-8 h-8 max-md:w-11 max-md:h-11 rounded-full btn-accent flex items-center justify-center disabled:opacity-30 transition shrink-0"
          >
            {busy ? <Square size={11} fill="currentColor" /> : <Send size={14} />}
          </button>
        </div>
      </div>
    </div>
  );
}
