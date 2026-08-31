import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, XCircle, Loader2, Circle, Send, ShieldAlert } from 'lucide-react';
import { agentSocket, getSettings } from '../lib/sidecar';

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

export default function AgentView() {
  const [goal, setGoal] = useState('');
  const [graph, setGraph] = useState<AgentGraph | null>(null);
  const [phase, setPhase] = useState<'idle' | 'planning' | 'running' | 'done' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);
  const [deviceAccess, setDeviceAccess] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    getSettings().then((s) => setDeviceAccess(s.agent_device_access));
  }, []);

  async function run() {
    if (!goal.trim() || phase === 'planning' || phase === 'running') return;
    setError(null);
    setGraph(null);
    setPhase('planning');
    const ws = await agentSocket();
    wsRef.current = ws;
    ws.onopen = () => ws.send(JSON.stringify({ goal: goal.trim() }));
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === 'planning') setPhase('planning');
      if (msg.type === 'graph') {
        setGraph(msg.graph);
        setPhase('running');
      }
      if (msg.type === 'done') {
        setGraph(msg.graph);
        setPhase('done');
      }
      if (msg.type === 'error') {
        setError(msg.message);
        setPhase('error');
      }
    };
    ws.onerror = () => setError('Connection to Uncloud engine lost');
  }

  const orderedTasks = graph ? Object.values(graph.tasks) : [];

  return (
    <div className="h-full flex flex-col">
      <header className="px-6 pt-5 pb-4 border-b border-[var(--border-soft)]">
        <h1 className="text-2xl font-semibold mb-1">Agent</h1>
        <p className="text-xs text-[var(--text-faint)]">
          Give Uncloud a goal — it plans a task graph with your local model and executes it with real tools.
        </p>
        {!deviceAccess && (
          <div className="flex items-center gap-1.5 text-[11px] text-amber-400/90 mt-2">
            <ShieldAlert size={12} /> Scoped to the Uncloud workspace folder. Enable full device access in Settings for unrestricted shell/filesystem.
          </div>
        )}
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

        {graph && (
          <div className="max-w-2xl flex flex-col gap-3">
            {orderedTasks.map((task) => (
              <div key={task.id} className="card p-4 flex gap-3">
                <div className="pt-0.5">
                  {task.status === 'completed' && <CheckCircle2 size={16} className="text-emerald-400" />}
                  {task.status === 'failed' && <XCircle size={16} className="text-rose-400" />}
                  {task.status === 'in_progress' && <Loader2 size={16} className="animate-spin text-[var(--text-dim)]" />}
                  {task.status === 'pending' && <Circle size={16} className="text-[var(--text-faint)]" />}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-sm">{task.description}</div>
                  <div className="text-[10px] font-mono text-[var(--text-faint)] mt-1 uppercase">{task.tool_id}</div>
                  {task.output && (
                    <pre className="text-[11px] text-[var(--text-dim)] mt-2 bg-[var(--bg-inset)] rounded-lg p-2 overflow-x-auto whitespace-pre-wrap">
                      {task.output.slice(0, 800)}
                    </pre>
                  )}
                  {task.error && <div className="text-[11px] text-rose-400 mt-2">{task.error}</div>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="p-4 border-t border-[var(--border-soft)]">
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
          <button
            onClick={run}
            disabled={!goal.trim() || phase === 'planning' || phase === 'running'}
            className="w-8 h-8 rounded-full bg-white text-black flex items-center justify-center disabled:opacity-30 disabled:bg-[var(--border)] disabled:text-[var(--text-faint)] transition shrink-0"
          >
            <Send size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}
