import { useState, useEffect, useRef } from 'react';
import { type ActiveStoryInfo, ActiveStoryBanner, PHASE_LABELS } from './ProjectDashboard';

// ── Workers tab (SSE live console) ────────────────────────────────────────────

interface WorkerInfo {
  id: number;
  hasLog: boolean;
  hasHeartbeat: boolean;
  hasJson?: boolean;
  mem_mb?: number | null;
  phase?: string | null;
  completed?: number;
  pid?: number | null;
  paused?: boolean;
  status_reason?: string;
  state?: string;
}

interface SystemMemoryInfo {
  watchdog_running: boolean;
  level: number | null;
  level_label: string | null;
  free_mb: number | null;
  total_mb: number | null;
  used_mb: number | null;
  free_pct: number | null;
  recommended_workers: number | null;
  per_worker_budget_mb: number;
  config_hints: string[];
}

type WorkerStatus = 'running' | 'passed' | 'failed' | 'unknown' | 'error';

function SystemMemoryPanel({ memory }: { memory: SystemMemoryInfo | null }) {
  if (!memory) return null;

  const { watchdog_running, level, level_label, free_mb, total_mb, used_mb, free_pct, recommended_workers, per_worker_budget_mb, config_hints } = memory;
  const [hintsExpanded, setHintsExpanded] = useState(false);

  if (!watchdog_running && level == null) {
    return (
      <div className="rounded-lg border border-slate-700 bg-slate-800/50 px-4 py-3 text-xs text-slate-400 flex items-center gap-2">
        <span className="text-slate-500">◯</span>
        Memory monitoring inactive — start SPIRAL with watchdog to enable
      </div>
    );
  }

  // Color for pressure level
  const levelColors: Record<number, { bg: string; text: string; bar: string }> = {
    0: { bg: 'bg-emerald-900/30', text: 'text-emerald-400', bar: 'bg-emerald-500' },
    1: { bg: 'bg-yellow-900/30', text: 'text-yellow-400', bar: 'bg-yellow-500' },
    2: { bg: 'bg-orange-900/30', text: 'text-orange-400', bar: 'bg-orange-500' },
    3: { bg: 'bg-red-900/30', text: 'text-red-400', bar: 'bg-red-500' },
    4: { bg: 'bg-red-900/50', text: 'text-red-300', bar: 'bg-red-600' },
  };
  const colors = levelColors[level ?? 0] ?? levelColors[0];
  const usedPct = free_pct != null ? 100 - free_pct : null;

  return (
    <div className={`rounded-lg border border-slate-700 ${colors.bg} px-4 py-3 space-y-2`}>
      <div className="flex items-center justify-between flex-wrap gap-2">
        {/* Memory bar */}
        <div className="flex items-center gap-3 flex-1 min-w-[200px]">
          <span className="text-xs font-semibold text-slate-300 whitespace-nowrap">RAM</span>
          <div className="flex-1 h-2.5 bg-slate-700 rounded-full overflow-hidden">
            {usedPct != null && (
              <div className={`h-full ${colors.bar} rounded-full transition-all duration-500`} style={{ width: `${Math.min(usedPct, 100)}%` }} />
            )}
          </div>
          <span className="text-[11px] font-mono text-slate-400 whitespace-nowrap">
            {used_mb != null && total_mb != null
              ? `${used_mb.toLocaleString()} / ${total_mb.toLocaleString()} MB (${free_pct}% free)`
              : free_mb != null ? `${free_mb.toLocaleString()} MB free` : '—'}
          </span>
        </div>

        {/* Pressure badge */}
        <span className={`text-[11px] font-mono font-semibold px-2 py-0.5 rounded-full ${colors.bg} ${colors.text} border border-current/20`}>
          {!watchdog_running && <span className="mr-1 opacity-60">STALE</span>}
          Level {level}: {level_label}
        </span>

        {/* Worker capacity */}
        {recommended_workers != null && (
          <span className="text-[11px] font-mono text-slate-400">
            Recommended: {recommended_workers} worker{recommended_workers !== 1 ? 's' : ''} ({per_worker_budget_mb} MB each)
          </span>
        )}
      </div>

      {/* Config hints */}
      {config_hints.length > 0 && (
        <div>
          <button
            onClick={() => setHintsExpanded(!hintsExpanded)}
            className="text-[11px] text-slate-500 hover:text-slate-300 transition-colors"
          >
            {hintsExpanded ? '▾' : '▸'} {config_hints.length} tuning hint{config_hints.length !== 1 ? 's' : ''}
          </button>
          {hintsExpanded && (
            <ul className="mt-1 space-y-0.5">
              {config_hints.map((hint, i) => (
                <li key={i} className="text-[11px] font-mono text-slate-400 pl-3">• {hint}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function WorkerConsole({ workerId, projectName, workerMeta }: { workerId: number; projectName: string; workerMeta?: WorkerInfo }) {
  const [lines, setLines] = useState<string[]>([]);
  const [status, setStatus] = useState<WorkerStatus>('running');
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const nameParam = projectName ? `&name=${encodeURIComponent(projectName)}` : '';
    const es = new EventSource(`/api/worker-stream/${workerId}?_=${nameParam}`);

    es.onmessage = (e: MessageEvent) => {
      try {
        const msg = JSON.parse(e.data as string) as { type: string; worker_id: number; data?: string; status?: string };
        if (msg.type === 'line' && msg.data) {
          setLines(prev => [...prev.slice(-500), msg.data!]); // cap at 500 lines
        } else if (msg.type === 'done') {
          const s = msg.status;
          setStatus(s === 'passed' ? 'passed' : s === 'failed' ? 'failed' : 'unknown');
          es.close();
        }
      } catch { /* ignore */ }
    };

    es.onerror = () => { setStatus('error'); es.close(); };

    return () => es.close();
  }, [workerId, projectName]);

  // Auto-scroll to bottom on new lines
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [lines]);

  const statusMeta: Record<WorkerStatus, { label: string; cls: string }> = {
    running: { label: '● Running', cls: 'text-emerald-400' },
    passed:  { label: '✓ Passed',  cls: 'text-emerald-400' },
    failed:  { label: '✗ Failed',  cls: 'text-red-400' },
    unknown: { label: '○ Done',    cls: 'text-slate-400' },
    error:   { label: '! Error',   cls: 'text-red-400' },
  };
  const { label, cls } = statusMeta[status];

  return (
    <div className="flex flex-col border border-slate-700 rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-3 py-1.5 bg-slate-800 border-b border-slate-700">
        <span className="text-xs font-mono font-semibold text-slate-200">Worker {workerId}</span>
        <div className="flex items-center gap-2">
          {workerMeta?.mem_mb != null && (
            <span className="text-[11px] font-mono text-slate-500">{workerMeta.mem_mb} MB</span>
          )}
          {workerMeta?.phase && (
            <span className="text-[11px] font-mono text-purple-400 bg-purple-900/30 px-1.5 py-0.5 rounded-full">{workerMeta.phase}</span>
          )}
          {workerMeta?.completed != null && workerMeta.completed > 0 && (
            <span className="text-[11px] font-mono text-emerald-400">{workerMeta.completed} done</span>
          )}
          {workerMeta?.paused && (
            <span className="text-[11px] font-mono text-amber-400 bg-amber-900/30 px-1.5 py-0.5 rounded-full">PAUSED</span>
          )}
          <span className={`text-xs font-mono ${cls}`}>{label}</span>
        </div>
      </div>
      <div className="h-72 overflow-y-auto bg-slate-950 p-2">
        {lines.length === 0 ? (
          <span className="text-xs font-mono text-slate-600">Waiting for output…</span>
        ) : (
          lines.map((line, i) => (
            <div key={i} className="text-[11px] font-mono leading-snug text-slate-300 whitespace-pre-wrap break-all">{line}</div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

export default function WorkersTab({
  projectName,
  activeStory,
  currentPhase,
  isRunning,
}: {
  projectName: string;
  activeStory: ActiveStoryInfo | null;
  currentPhase: string | null;
  isRunning: boolean;
}) {
  const [workers, setWorkers] = useState<WorkerInfo[]>([]);
  const [systemMemory, setSystemMemory] = useState<SystemMemoryInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);

  useEffect(() => {
    const nameParam = projectName ? `?name=${encodeURIComponent(projectName)}` : '';
    const fetchAll = () => {
      Promise.allSettled([
        fetch(`/api/workers${nameParam}`).then(r => r.json() as Promise<{ workers?: WorkerInfo[]; error?: string }>),
        fetch(`/api/system-memory${nameParam}`).then(r => r.json() as Promise<SystemMemoryInfo>),
      ]).then(([workersResult, memoryResult]) => {
        if (workersResult.status === 'fulfilled') {
          const d = workersResult.value;
          if (d.error) setFetchError(d.error);
          else setWorkers(d.workers ?? []);
        } else {
          setFetchError(String(workersResult.reason));
        }
        if (memoryResult.status === 'fulfilled') {
          setSystemMemory(memoryResult.value);
        }
        setLoading(false);
      });
    };
    fetchAll();
    const interval = setInterval(fetchAll, 5000);
    return () => clearInterval(interval);
  }, [projectName]);

  if (loading) return <div className="p-6 text-sm text-slate-500">Loading workers…</div>;
  if (fetchError) return <div className="p-6 text-sm text-red-500">Error: {fetchError}</div>;

  // Phase-aware idle detection
  const allQueuedOrDefault = workers.length > 0 && workers.every(w => w.state === 'queued' || (!w.hasLog && !w.hasHeartbeat));
  const inNonWorkerPhase = isRunning && currentPhase != null && currentPhase !== 'I';

  // SPIRAL is running but not in Phase I — workers are expected to be idle
  if (inNonWorkerPhase && allQueuedOrDefault) {
    const phaseName = PHASE_LABELS[currentPhase] ?? `Phase ${currentPhase}`;
    return (
      <div className="p-6 space-y-4">
        <ActiveStoryBanner activeStory={activeStory} />
        <SystemMemoryPanel memory={systemMemory} />
        <div className="text-center text-slate-500 py-10">
          <div className="text-2xl mb-2">⏳</div>
          <div className="text-sm font-medium text-slate-600 mb-1">Workers idle</div>
          <div className="text-xs text-slate-400 max-w-sm mx-auto">
            SPIRAL is currently <span className="font-semibold text-blue-600">{phaseName}</span>. Workers are only active during the <span className="font-semibold">Implementing</span> phase.
          </div>
          <div className="text-[11px] text-slate-400 mt-2">
            {workers.length} worker{workers.length !== 1 ? 's' : ''} will resume when Phase I starts
          </div>
        </div>
      </div>
    );
  }

  // SPIRAL is idle but stale worker files exist from a previous run
  if (!isRunning && allQueuedOrDefault && workers.length > 0) {
    return (
      <div className="p-6 space-y-4">
        <SystemMemoryPanel memory={systemMemory} />
        <div className="text-center text-slate-500 py-10">
          <div className="text-2xl mb-2">👷</div>
          <div className="text-sm font-medium">No active workers</div>
          <div className="text-xs mt-1 text-slate-400">
            SPIRAL is idle. {workers.length} worker file{workers.length !== 1 ? 's exist' : ' exists'} from a previous run.
          </div>
        </div>
      </div>
    );
  }

  if (workers.length === 0) {
    return (
      <div className="p-6 space-y-4">
        <ActiveStoryBanner activeStory={activeStory} />
        <SystemMemoryPanel memory={systemMemory} />
        <div className="text-center text-slate-500">
          <div className="text-2xl mb-2">👷</div>
          <div className="text-sm font-medium">No workers found</div>
          <div className="text-xs mt-1 text-slate-400">
            Run <code className="bg-slate-100 px-1 rounded">bash spiral.sh 5 --ralph-workers 2</code> to launch parallel workers and see live output here.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 space-y-4">
      <ActiveStoryBanner activeStory={activeStory} />
      <SystemMemoryPanel memory={systemMemory} />
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {workers.map(w => {
          if (w.state === 'queued') {
            return (
              <div key={w.id} className="flex flex-col border border-dashed border-slate-600 rounded-lg overflow-hidden opacity-70">
                <div className="flex items-center justify-between px-3 py-1.5 bg-slate-800/50 border-b border-slate-700">
                  <span className="text-xs font-mono font-semibold text-slate-400">Worker {w.id}</span>
                  <span className="text-xs font-mono text-slate-500">◌ Queued</span>
                </div>
                <div className="h-24 flex items-center justify-center bg-slate-950/50 p-3">
                  <span className="text-xs font-mono text-slate-500 text-center">
                    {w.status_reason || `Waiting for ${systemMemory?.per_worker_budget_mb ?? 1536} MB free RAM to launch`}
                  </span>
                </div>
              </div>
            );
          }
          if (w.paused) {
            return (
              <div key={w.id} className="flex flex-col border border-amber-700/50 rounded-lg overflow-hidden">
                <div className="flex items-center justify-between px-3 py-1.5 bg-amber-900/20 border-b border-amber-700/30">
                  <span className="text-xs font-mono font-semibold text-slate-200">Worker {w.id}</span>
                  <div className="flex items-center gap-2">
                    {w.mem_mb != null && <span className="text-[11px] font-mono text-slate-500">{w.mem_mb} MB</span>}
                    <span className="text-xs font-mono text-amber-400 bg-amber-900/40 px-1.5 py-0.5 rounded-full">PAUSED</span>
                  </div>
                </div>
                <div className="h-24 flex items-center justify-center bg-slate-950 p-3">
                  <span className="text-xs font-mono text-amber-400/70 text-center">{w.status_reason || 'Paused — memory pressure'}</span>
                </div>
              </div>
            );
          }
          return w.hasLog
            ? <WorkerConsole key={w.id} workerId={w.id} projectName={projectName} workerMeta={w} />
            : (
              <div key={w.id} className="flex flex-col border border-slate-700 rounded-lg overflow-hidden">
                <div className="flex items-center justify-between px-3 py-1.5 bg-slate-800 border-b border-slate-700">
                  <span className="text-xs font-mono font-semibold text-slate-200">Worker {w.id}</span>
                  <div className="flex items-center gap-2">
                    {w.mem_mb != null && <span className="text-[11px] font-mono text-slate-500">{w.mem_mb} MB</span>}
                    {w.phase && <span className="text-[11px] font-mono text-purple-400 bg-purple-900/30 px-1.5 py-0.5 rounded-full">{w.phase}</span>}
                    {(w.completed ?? 0) > 0 && <span className="text-[11px] font-mono text-emerald-400">{w.completed} done</span>}
                    <span className="text-xs font-mono text-slate-400">○ Completed (no log)</span>
                  </div>
                </div>
                <div className="h-32 flex items-center justify-center bg-slate-950 p-2">
                  <span className="text-xs font-mono text-slate-600">
                    PRD slice assigned — log not available.{w.hasHeartbeat ? ' Heartbeat active.' : ''}
                  </span>
                </div>
              </div>
            );
        })}
      </div>
    </div>
  );
}
