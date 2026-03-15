import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import DependencyGraph from './DependencyGraph';
import { CONFIG_FIELDS } from '../data/configSchema';

// Config description lookup for tooltips in Settings tab
const CONFIG_DESCRIPTIONS: Record<string, { label: string; description: string }> = Object.fromEntries(
  CONFIG_FIELDS.map(f => [f.key, { label: f.label, description: f.description }])
);

// ── Types ────────────────────────────────────────────────────────────────────

interface Story {
  id: string;
  title: string;
  passes: boolean;
  priority?: string;
  complexity?: string;
  failureReason?: string;
  dependencies?: string[];
  status?: string;
}

interface ProgressData {
  total: number;
  done: number;
  pending: number;
  productName?: string;
  overview?: string;
  stories: Story[];
}

interface ProgressSnapshot {
  ts: string;
  iter: number;
  done: number;
  pending: number;
  total: number;
  added: number;
}

interface TokenBurnEntry {
  story_id: string;
  input: number;
  output: number;
  total: number;
  calls: number;
}

interface CachePhaseEntry {
  phase: string;
  hit_rate: number;
  hits: number;
  total: number;
  creation_tokens: number;
  read_tokens: number;
}

interface LastCompletedStory {
  id: string;
  title: string;
  timestamp: string;
  model?: string;
  duration?: number;
}

interface ProjectData {
  name: string;
  root: string;
  lastSeen: string;
  progress: ProgressData | null;
  config: Record<string, string>;
  constitution: string;
  activity: string;
  progressHistory: ProgressSnapshot[];
  tokenBurn?: TokenBurnEntry[];
  cacheStats?: CachePhaseEntry[];
  lastCompletedStory?: LastCompletedStory | null;
  checkpointTs?: string | null;
  lastLogModified?: string | null;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Format Malaysia Time (MYT, UTC+8) from an ISO string. */
function formatMYT(ts: string): string {
  try {
    return new Date(ts).toLocaleString('en-MY', { timeZone: 'Asia/Kuala_Lumpur', hour12: false });
  } catch { return ts; }
}

function timeAgo(ts: string) {
  const s = Math.floor((Date.now() - new Date(ts).getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m ago`;
}

function pct(done: number, total: number) {
  return total > 0 ? Math.round((done / total) * 100) : 0;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function ProgressTab({ data }: { data: ProjectData }) {
  const p = data.progress;
  if (!p) return <div className="p-6 text-slate-500">No prd.json found in project root.</div>;

  const PRIORITY_RANK: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
  const done = p.stories.filter(s => s.passes);
  const pending = [...p.stories.filter(s => !s.passes)]
    .sort((a, b) => (PRIORITY_RANK[a.priority ?? 'low'] ?? 99) - (PRIORITY_RANK[b.priority ?? 'low'] ?? 99));
  const donePct = pct(p.done, p.total);

  return (
    <div className="p-6 space-y-6">
      {/* Last completed story indicator */}
      {data.lastCompletedStory && (
        <div className="flex items-center gap-3 rounded-xl border border-emerald-200 bg-emerald-50/50 px-4 py-2.5">
          <span className="text-emerald-500 text-lg">&#10003;</span>
          <div className="flex-1 min-w-0">
            <span className="text-xs text-slate-500">Last story completed:</span>
            <span className="ml-2 text-sm font-mono font-semibold text-emerald-700">{data.lastCompletedStory.id}</span>
            {data.lastCompletedStory.title && (
              <span className="ml-1.5 text-sm text-slate-600">{data.lastCompletedStory.title}</span>
            )}
          </div>
          <div className="flex items-center gap-3 flex-shrink-0">
            {data.lastCompletedStory.model && (
              <span className="text-[10px] bg-white/80 text-slate-500 px-2 py-0.5 rounded-full border border-slate-200">{data.lastCompletedStory.model}</span>
            )}
            {(data.lastCompletedStory.duration ?? 0) > 0 && (
              <span className="text-[10px] bg-white/80 text-slate-500 px-2 py-0.5 rounded-full border border-slate-200">
                {(data.lastCompletedStory.duration ?? 0) >= 60
                  ? `${Math.floor((data.lastCompletedStory.duration ?? 0) / 60)}m ${(data.lastCompletedStory.duration ?? 0) % 60}s`
                  : `${data.lastCompletedStory.duration}s`}
              </span>
            )}
            <span className="text-xs font-medium text-emerald-600" title={new Date(data.lastCompletedStory.timestamp).toLocaleString()}>
              {timeAgo(data.lastCompletedStory.timestamp)}
            </span>
          </div>
        </div>
      )}

      {/* Stats cards */}
      <div className="grid grid-cols-3 gap-4">
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
          <div className="text-3xl font-bold text-emerald-700">{donePct}%</div>
          <div className="text-sm text-emerald-600 mt-0.5">{p.done} / {p.total} stories complete</div>
        </div>
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
          <div className="text-3xl font-bold text-amber-700">{p.pending}</div>
          <div className="text-sm text-amber-600 mt-0.5">stories pending</div>
        </div>
        <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
          <div className="text-3xl font-bold text-blue-700">{p.total}</div>
          <div className="text-sm text-blue-600 mt-0.5">total stories</div>
        </div>
      </div>

      {/* Progress bar */}
      <div>
        <div className="flex justify-between text-xs text-slate-500 mb-1">
          <span>Progress</span><span>{p.done} done · {p.pending} remaining</span>
        </div>
        <div className="h-3 rounded-full bg-slate-200 overflow-hidden">
          <div
            className="h-full rounded-full bg-emerald-500 transition-all duration-500"
            style={{ width: `${donePct}%` }}
          />
        </div>
      </div>

      {/* Progress history sparkline */}
      {data.progressHistory.length > 1 && (
        <div>
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Progress History</div>
          <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-slate-500">
                <tr>
                  <th className="px-3 py-2 text-left">Time</th>
                  <th className="px-3 py-2 text-left">Iter</th>
                  <th className="px-3 py-2 text-right">Done</th>
                  <th className="px-3 py-2 text-right">Pending</th>
                  <th className="px-3 py-2 text-right">Added</th>
                </tr>
              </thead>
              <tbody>
                {[...data.progressHistory].reverse().slice(0, 12).map((snap, i) => (
                  <tr key={i} className="border-t border-slate-100">
                    <td className="px-3 py-1.5 text-slate-400" title={formatMYT(snap.ts)}>{timeAgo(snap.ts)}</td>
                    <td className="px-3 py-1.5 text-slate-600">#{snap.iter}</td>
                    <td className="px-3 py-1.5 text-right font-mono text-emerald-700">{snap.done}</td>
                    <td className="px-3 py-1.5 text-right font-mono text-amber-700">{snap.pending}</td>
                    <td className="px-3 py-1.5 text-right font-mono text-blue-700">+{snap.added}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Token burn sparkline (US-189) */}
      {data.tokenBurn && data.tokenBurn.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Token Burn by Story</div>
          <TokenBurnSparkline entries={data.tokenBurn} />
        </div>
      )}

      {/* Prompt cache hit rate by phase (US-223) */}
      {data.cacheStats && data.cacheStats.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Prompt Cache Hit Rate by Phase</div>
          <CacheStatsTable entries={data.cacheStats} />
        </div>
      )}

      {/* Story lists */}
      {pending.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-amber-600 uppercase tracking-wide mb-2">Pending ({pending.length})</div>
          <div className="space-y-1">
            {pending.map(s => (
              <div key={s.id} className="flex items-start gap-2 rounded-lg border border-amber-100 bg-amber-50 px-3 py-2">
                <span className="text-amber-400 mt-0.5">○</span>
                <div className="flex-1 min-w-0">
                  <span className="text-xs font-mono text-amber-700">{s.id}</span>
                  <span className="ml-2 text-xs text-slate-700">{s.title}</span>
                </div>
                {s.priority && (
                  <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                    s.priority === 'critical' ? 'bg-red-100 text-red-700' :
                    s.priority === 'high' ? 'bg-orange-100 text-orange-700' :
                    s.priority === 'medium' ? 'bg-yellow-100 text-yellow-700' :
                    'bg-slate-100 text-slate-500'
                  }`}>{s.priority}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {done.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-emerald-600 uppercase tracking-wide mb-2">Complete ({done.length})</div>
          <div className="space-y-1">
            {done.map(s => (
              <div key={s.id} className="flex items-start gap-2 rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-2">
                <span className="text-emerald-500 mt-0.5">✓</span>
                <span className="text-xs font-mono text-emerald-700">{s.id}</span>
                <span className="ml-1 text-xs text-slate-600">{s.title}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function TokenBurnSparkline({ entries }: { entries: TokenBurnEntry[] }) {
  if (entries.length === 0) {
    return (
      <div className="text-xs text-slate-400 italic">
        No token data yet. Token metrics are recorded after each Phase I run.
      </div>
    );
  }

  // Sort by total tokens descending for the table
  const sorted = [...entries].sort((a, b) => b.total - a.total);
  const maxTotal = sorted[0]?.total ?? 1;

  function fmtK(n: number) {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
    return String(n);
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
      <table className="w-full text-xs">
        <thead className="bg-slate-50 text-slate-500">
          <tr>
            <th className="px-3 py-2 text-left">Story</th>
            <th className="px-3 py-2 text-right">Input</th>
            <th className="px-3 py-2 text-right">Output</th>
            <th className="px-3 py-2 text-right">Total</th>
            <th className="px-3 py-2 w-32">Burn</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map(e => {
            const barPct = maxTotal > 0 ? Math.round((e.total / maxTotal) * 100) : 0;
            return (
              <tr key={e.story_id} className="border-t border-slate-100 hover:bg-slate-50">
                <td className="px-3 py-1.5 font-mono text-blue-700 whitespace-nowrap">{e.story_id}</td>
                <td className="px-3 py-1.5 text-right text-slate-500">{fmtK(e.input)}</td>
                <td className="px-3 py-1.5 text-right text-slate-500">{fmtK(e.output)}</td>
                <td className="px-3 py-1.5 text-right font-medium text-slate-700">{fmtK(e.total)}</td>
                <td className="px-3 py-1.5">
                  <div className="flex items-center gap-1.5">
                    <div className="flex-1 h-2 rounded-full bg-slate-100 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-violet-500"
                        style={{ width: `${barPct}%` }}
                      />
                    </div>
                    <span className="text-[10px] text-slate-400 w-8 text-right">{barPct}%</span>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function CacheStatsTable({ entries }: { entries: CachePhaseEntry[] }) {
  function fmtK(n: number) {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
    return String(n);
  }
  const sorted = [...entries].sort((a, b) => a.phase.localeCompare(b.phase));
  return (
    <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
      <table className="w-full text-xs">
        <thead className="bg-slate-50 text-slate-500">
          <tr>
            <th className="px-3 py-2 text-left">Phase</th>
            <th className="px-3 py-2 text-right">Hits / Calls</th>
            <th className="px-3 py-2 text-right">Hit Rate</th>
            <th className="px-3 py-2 text-right">Cache Read Tokens</th>
            <th className="px-3 py-2 w-28">Rate</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map(e => {
            const pct = Math.round(e.hit_rate * 100);
            return (
              <tr key={e.phase} className="border-t border-slate-100 hover:bg-slate-50">
                <td className="px-3 py-1.5 font-mono font-semibold text-blue-700">{e.phase}</td>
                <td className="px-3 py-1.5 text-right text-slate-500">{e.hits}/{e.total}</td>
                <td className="px-3 py-1.5 text-right font-medium text-slate-700">{pct}%</td>
                <td className="px-3 py-1.5 text-right text-emerald-700">{fmtK(e.read_tokens)}</td>
                <td className="px-3 py-1.5">
                  <div className="flex items-center gap-1.5">
                    <div className="flex-1 h-2 rounded-full bg-slate-100 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-emerald-500"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="text-[10px] text-slate-400 w-8 text-right">{pct}%</span>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SettingsTab({ config }: { config: Record<string, string> }) {
  const entries = Object.entries(config).filter(([, v]) => v !== '' && v !== '0' && v !== 'false');
  if (entries.length === 0) {
    return <div className="p-6 text-slate-500">No active settings found in spiral.config.sh.</div>;
  }
  return (
    <div className="p-6">
      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-slate-50 text-slate-500">
            <tr>
              <th className="px-4 py-2.5 text-left font-medium">Variable</th>
              <th className="px-4 py-2.5 text-left font-medium">Value</th>
            </tr>
          </thead>
          <tbody>
            {entries.map(([k, v]) => {
              const meta = CONFIG_DESCRIPTIONS[k];
              return (
                <tr key={k} className="border-t border-slate-100 hover:bg-slate-50">
                  <td className="px-4 py-2">
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono text-blue-700 whitespace-nowrap">{k}</span>
                      {meta && (
                        <span
                          className="inline-flex items-center justify-center w-4 h-4 rounded-full bg-slate-200 text-slate-500 text-[9px] font-bold cursor-help flex-shrink-0"
                          title={`${meta.label}\n\n${meta.description}`}
                        >
                          ?
                        </span>
                      )}
                    </div>
                    {meta && <div className="text-[10px] text-slate-400 mt-0.5">{meta.label}</div>}
                  </td>
                  <td className="px-4 py-2 font-mono text-slate-700 break-all">{v}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ConstitutionTab({ text }: { text: string }) {
  if (!text) {
    return (
      <div className="p-6 text-slate-500">
        No constitution found. Set <code className="bg-slate-100 px-1 rounded">SPIRAL_SPECKIT_CONSTITUTION</code> in your config,
        or create <code className="bg-slate-100 px-1 rounded">.specify/memory/constitution.md</code> in your project root.
      </div>
    );
  }
  return (
    <div className="p-6">
      <div className="rounded-xl border border-slate-200 bg-white p-5 prose prose-sm max-w-none">
        <pre className="whitespace-pre-wrap text-xs text-slate-700 font-mono leading-relaxed">{text}</pre>
      </div>
    </div>
  );
}

/** Convert ISO/UTC timestamps in a log line to Malaysia time (MYT, UTC+8). */
function toMYT(line: string): string {
  // Match ISO timestamps: 2026-03-16T10:30:45Z or 2026-03-16T10:30:45.123Z or +00:00
  return line.replace(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})/g, (match) => {
    try {
      return new Date(match).toLocaleString('en-MY', { timeZone: 'Asia/Kuala_Lumpur', hour12: false, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch { return match; }
  });
}

function ActivityTab({ log }: { log: string }) {
  if (!log) {
    return <div className="p-6 text-slate-500">No activity log yet. Start SPIRAL to see live output here.</div>;
  }
  const lines = log.split('\n').filter(Boolean);
  const now = new Date().toLocaleString('en-MY', { timeZone: 'Asia/Kuala_Lumpur', hour12: false });
  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-2">
        <div className="text-[10px] text-slate-400">Timestamps shown in Malaysia Time (MYT, UTC+8)</div>
        <div className="text-[10px] text-slate-400">Now: {now}</div>
      </div>
      <div className="rounded-xl bg-slate-950 overflow-auto max-h-[600px]">
        <pre className="p-4 text-[11px] text-slate-300 font-mono leading-relaxed whitespace-pre-wrap">
          {lines.map(toMYT).join('\n')}
        </pre>
      </div>
    </div>
  );
}

// ── Phase Trace types ────────────────────────────────────────────────────────

interface Substep {
  id: string;
  label: string;
  lines: string[];
  lineStart: number;
  lineEnd: number;
}

interface IterPhase {
  phase: string;
  label: string;
  lines: string[];
  lineStart: number;
  lineEnd: number;
  substeps?: Substep[];
}

interface Iteration {
  iter: number;
  phases: IterPhase[];
  lineStart: number;
  lineEnd: number;
}

interface PhaseOutputs {
  aiSuggestions: { stories?: unknown[] } | null;
  research: { stories?: unknown[] } | null;
  testStories: { stories?: unknown[] } | null;
  validated: { stories?: unknown[] } | null;
  overflow: { stories?: unknown[] } | null;
  checkpoint: { iter?: number; phase?: string; ts?: string } | null;
}

interface PhaseTraceData {
  iterations: Iteration[];
  phaseOutputs: PhaseOutputs;
  phaseEvents: Array<{ event?: string; type?: string; phase?: string; iteration?: number; duration_s?: number; ts?: string }>;
}

const PHASE_COLORS: Record<string, { bg: string; border: string; text: string; dot: string }> = {
  '0': { bg: 'bg-slate-50',   border: 'border-slate-300',   text: 'text-slate-700',   dot: 'bg-slate-500' },
  A:   { bg: 'bg-indigo-50',  border: 'border-indigo-200',  text: 'text-indigo-700',  dot: 'bg-indigo-500' },
  R:   { bg: 'bg-blue-50',    border: 'border-blue-200',    text: 'text-blue-700',    dot: 'bg-blue-500' },
  T:   { bg: 'bg-violet-50',  border: 'border-violet-200',  text: 'text-violet-700',  dot: 'bg-violet-500' },
  S:   { bg: 'bg-cyan-50',    border: 'border-cyan-200',    text: 'text-cyan-700',    dot: 'bg-cyan-500' },
  M:   { bg: 'bg-amber-50',   border: 'border-amber-200',   text: 'text-amber-700',   dot: 'bg-amber-500' },
  I:   { bg: 'bg-emerald-50', border: 'border-emerald-200', text: 'text-emerald-700', dot: 'bg-emerald-500' },
  V:   { bg: 'bg-teal-50',    border: 'border-teal-200',    text: 'text-teal-700',    dot: 'bg-teal-500' },
  P:   { bg: 'bg-purple-50',  border: 'border-purple-200',  text: 'text-purple-700',  dot: 'bg-purple-500' },
  C:   { bg: 'bg-rose-50',    border: 'border-rose-200',    text: 'text-rose-700',    dot: 'bg-rose-500' },
  D:   { bg: 'bg-orange-50',  border: 'border-orange-200',  text: 'text-orange-700',  dot: 'bg-orange-500' },
};

const PHASE_NAMES: Record<string, string> = {
  '0': 'Clarify (Session Setup)', A: 'AI Suggestions', R: 'Research', T: 'Test Synthesis',
  S: 'Story Validate', M: 'Merge',
  I: 'Implement', V: 'Validate', P: 'Push', C: 'Check Done', D: 'Loop Decision',
};

const SUBSTEP_NAMES: Record<string, string> = {
  '0-A': 'Constitution', '0-B': 'Focus', '0-C': 'Clarify', '0-D': 'Story Prep', '0-E': 'Options',
  'I/decompose': 'Decompose', 'I/retry': 'Retry', 'I/commit': 'Commit', 'I/revert': 'Revert',
  'I.5': 'Self-Review',
  'test-ratchet': 'Test Ratchet', 'security-scan': 'Security Scan', 'tag': 'Git Tag', 'CAPACITY': 'Capacity Guard',
};

/** Canonical phase order — phases sort by this index in the timeline. */
const PHASE_ORDER: Record<string, number> = {
  '0': 0, A: 1, R: 2, T: 3, S: 4, M: 5, I: 6, V: 7, P: 8, C: 9, D: 10,
};

function PhaseTraceTab({ projectName }: { projectName: string }) {
  const [traceData, setTraceData] = useState<PhaseTraceData | null>(null);
  const [selectedIter, setSelectedIter] = useState<number | null>(null);
  const [expandedPhases, setExpandedPhases] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const userSelectedRef = useRef(false);

  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetch(`/api/phase-trace?name=${encodeURIComponent(projectName)}`);
        if (res.ok) {
          const data = await res.json() as PhaseTraceData;
          setTraceData(data);
          // Auto-select latest iteration only on first load (before user clicks)
          if (data.iterations.length > 0 && !userSelectedRef.current) {
            setSelectedIter(data.iterations[data.iterations.length - 1].iter);
          }
        }
      } catch { /* ignore */ }
      setLoading(false);
    };
    load();
    const interval = setInterval(load, 15_000);
    return () => clearInterval(interval);
  }, [projectName]);

  if (loading) return <div className="p-6 text-slate-500">Loading phase trace data...</div>;
  if (!traceData || traceData.iterations.length === 0) {
    return (
      <div className="p-6 text-slate-500">
        No phase trace data yet. Start SPIRAL to see phase-by-phase output here.
        <div className="mt-2 text-xs text-slate-400">
          Phase traces are parsed from <code className="bg-slate-100 px-1 rounded">.spiral/_last_run.log</code>
        </div>
      </div>
    );
  }

  const togglePhase = (key: string) => {
    setExpandedPhases(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  const currentIter = traceData.iterations.find(i => i.iter === selectedIter) ?? traceData.iterations[traceData.iterations.length - 1];

  // Find phase_end events for duration display
  const phaseEndEvents = traceData.phaseEvents.filter(
    e => (e.event === 'phase_end' || e.type === 'phase_end') && e.iteration === currentIter.iter
  );

  const getDuration = (phase: string): number | null => {
    const ev = phaseEndEvents.find(e => e.phase === phase);
    return ev?.duration_s ?? null;
  };

  // Phase output file summary
  const outputSummary = (phase: string): string | null => {
    if (phase === 'A' && traceData.phaseOutputs.aiSuggestions) {
      const count = traceData.phaseOutputs.aiSuggestions.stories?.length ?? 0;
      return count > 0 ? `${count} ai suggestions` : 'No suggestions';
    }
    if (phase === 'R' && traceData.phaseOutputs.research) {
      const count = traceData.phaseOutputs.research.stories?.length ?? 0;
      return count > 0 ? `${count} research stories` : 'No stories found';
    }
    if (phase === 'T' && traceData.phaseOutputs.testStories) {
      const count = traceData.phaseOutputs.testStories.stories?.length ?? 0;
      return count > 0 ? `${count} test-fix stories` : 'No test failures';
    }
    if (phase === 'S' && traceData.phaseOutputs.validated) {
      const count = traceData.phaseOutputs.validated.stories?.length ?? 0;
      return count > 0 ? `${count} validated stories` : 'No stories validated';
    }
    return null;
  };

  return (
    <div className="p-6 space-y-4">
      {/* Checkpoint status */}
      {traceData.phaseOutputs.checkpoint && (
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <span className="font-medium">Checkpoint:</span>
          <span>Iteration {traceData.phaseOutputs.checkpoint.iter}, Phase {traceData.phaseOutputs.checkpoint.phase}</span>
          {traceData.phaseOutputs.checkpoint.ts && (
            <span className="text-slate-400">({timeAgo(traceData.phaseOutputs.checkpoint.ts)})</span>
          )}
        </div>
      )}

      {/* Iteration selector */}
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide">Iteration:</span>
        <div className="flex gap-1 flex-wrap">
          {traceData.iterations.map(iter => (
            <button
              key={iter.iter}
              onClick={() => { userSelectedRef.current = true; setSelectedIter(iter.iter); setExpandedPhases(new Set()); }}
              className={`px-2.5 py-1 text-xs font-mono rounded-lg border transition-colors ${
                iter.iter === currentIter.iter
                  ? 'bg-blue-600 text-white border-blue-600'
                  : 'bg-white text-slate-600 border-slate-200 hover:border-blue-300 hover:bg-blue-50'
              }`}
            >
              #{iter.iter}
            </button>
          ))}
        </div>
        <span className="text-xs text-slate-400 ml-2">{currentIter.phases.filter(p => p.phase !== 'G').length} phases</span>
      </div>

      {/* Phase timeline */}
      <div className="space-y-2">
        {currentIter.phases
        .filter(p => p.phase !== 'G')
        .sort((a, b) => (PHASE_ORDER[a.phase] ?? 99) - (PHASE_ORDER[b.phase] ?? 99))
        .map((phase, idx) => {
          const colors = PHASE_COLORS[phase.phase] ?? { bg: 'bg-slate-50', border: 'border-slate-200', text: 'text-slate-700', dot: 'bg-slate-500' };
          const phaseName = PHASE_NAMES[phase.phase] ?? `Phase ${phase.phase}`;
          const duration = getDuration(phase.phase);
          const summary = outputSummary(phase.phase);
          const key = `${currentIter.iter}-${phase.phase}-${idx}`;
          const isExpanded = expandedPhases.has(key);
          const lineCount = phase.lines.length;
          const substeps: Substep[] = (phase as IterPhase & { substeps?: Substep[] }).substeps ?? [];
          const hasSubsteps = substeps.length > 0;
          const isSkipped = phase.label.endsWith('(not run)') || phase.lineStart === -1;

          return (
            <div key={key} className={`rounded-xl border ${isSkipped ? 'border-slate-200 bg-slate-50/50' : `${colors.border} ${colors.bg}`} overflow-hidden ${isSkipped ? 'opacity-50' : ''}`}>
              {/* Phase header */}
              <button
                onClick={() => !isSkipped && togglePhase(key)}
                className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-opacity ${isSkipped ? 'cursor-default' : 'hover:opacity-90'}`}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <div className={`w-2.5 h-2.5 rounded-full ${colors.dot} flex-shrink-0`} />
                  <span className={`text-xs font-bold ${colors.text} font-mono`}>Phase {phase.phase}</span>
                  <span className={`text-xs font-semibold ${colors.text}`}>{phaseName}</span>
                </div>
                {phase.label && phase.label !== phaseName && (
                  <span className="text-xs text-slate-500 truncate">{phase.label}</span>
                )}
                <div className="ml-auto flex items-center gap-3 flex-shrink-0">
                  {isSkipped && <span className="text-[10px] text-slate-400 bg-slate-200 px-2 py-0.5 rounded-full font-medium">SKIPPED</span>}
                  {!isSkipped && summary && <span className="text-[10px] text-slate-500 bg-white/60 px-2 py-0.5 rounded-full">{summary}</span>}
                  {!isSkipped && hasSubsteps && <span className="text-[10px] text-slate-500 bg-white/60 px-2 py-0.5 rounded-full">{substeps.length} steps</span>}
                  {!isSkipped && duration !== null && (
                    <span className="text-[10px] font-mono text-slate-500 bg-white/60 px-2 py-0.5 rounded-full">
                      {duration >= 60 ? `${Math.floor(duration / 60)}m ${duration % 60}s` : `${duration}s`}
                    </span>
                  )}
                  {!isSkipped && <span className="text-[10px] text-slate-400">{lineCount} lines</span>}
                  {!isSkipped && <span className={`text-xs text-slate-400 transition-transform ${isExpanded ? 'rotate-180' : ''}`}>▼</span>}
                </div>
              </button>

              {/* Phase detail (expanded) */}
              {isExpanded && (
                <div className="border-t border-slate-200/50">
                  {/* Sub-steps list */}
                  {hasSubsteps && (
                    <div className="px-4 py-3 space-y-1.5 border-b border-slate-200/50 bg-white/40">
                      <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Steps</div>
                      {substeps.map((sub: Substep, si: number) => {
                        const subKey = `${key}-sub-${si}`;
                        const subExpanded = expandedPhases.has(subKey);
                        const subName = SUBSTEP_NAMES[sub.id] ?? sub.id;
                        return (
                          <div key={subKey} className="rounded-lg border border-slate-200 bg-white overflow-hidden">
                            <button
                              onClick={(e) => { e.stopPropagation(); togglePhase(subKey); }}
                              className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-slate-50 transition-colors"
                            >
                              <span className="w-1.5 h-1.5 rounded-full bg-slate-400 flex-shrink-0" />
                              <span className="text-[11px] font-mono font-semibold text-slate-600">{sub.id}</span>
                              <span className="text-[11px] text-slate-500">{subName}</span>
                              {sub.label && sub.label !== subName && (
                                <span className="text-[10px] text-slate-400 truncate ml-1">{sub.label}</span>
                              )}
                              <span className="ml-auto text-[10px] text-slate-400">{sub.lines.length} lines</span>
                              <span className={`text-[10px] text-slate-400 transition-transform ${subExpanded ? 'rotate-180' : ''}`}>▼</span>
                            </button>
                            {subExpanded && (
                              <div className="border-t border-slate-100 bg-slate-950 overflow-auto max-h-[250px]">
                                <pre className="p-2.5 text-[10px] text-slate-300 font-mono leading-relaxed whitespace-pre-wrap">
                                  {sub.lines.join('\n')}
                                </pre>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* Full phase log output */}
                  <div className="bg-slate-950 overflow-auto max-h-[400px]">
                    <pre className="p-3 text-[11px] text-slate-300 font-mono leading-relaxed whitespace-pre-wrap">
                      {phase.lines.join('\n')}
                    </pre>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Phase output files summary */}
      <div>
        <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Phase Output Files (Current)</div>
        <div className="grid grid-cols-2 gap-2">
          {[
            { label: 'AI Suggestions', key: 'aiSuggestions' as const, phase: 'A' },
            { label: 'Research Output', key: 'research' as const, phase: 'R' },
            { label: 'Test Stories', key: 'testStories' as const, phase: 'T' },
            { label: 'Validated Stories', key: 'validated' as const, phase: 'S' },
            { label: 'Overflow Queue', key: 'overflow' as const, phase: 'M' },
          ].map(item => {
            const data = traceData.phaseOutputs[item.key];
            const count = (data as { stories?: unknown[] } | null)?.stories?.length ?? 0;
            const colors = PHASE_COLORS[item.phase] ?? { bg: 'bg-slate-50', border: 'border-slate-200', text: 'text-slate-700', dot: 'bg-slate-400' };
            return (
              <div key={item.key} className={`rounded-lg border ${colors.border} ${colors.bg} px-3 py-2 flex items-center justify-between`}>
                <div className="flex items-center gap-2">
                  <div className={`w-2 h-2 rounded-full ${colors.dot}`} />
                  <span className={`text-xs font-medium ${colors.text}`}>{item.label}</span>
                </div>
                <span className={`text-xs font-mono ${count > 0 ? colors.text : 'text-slate-400'}`}>
                  {data ? `${count} stories` : 'N/A'}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

type DashTab = 'progress' | 'settings' | 'constitution' | 'activity' | 'graph' | 'phase-trace';

const DASH_TABS: { id: DashTab; slug: string; label: string; icon: string }[] = [
  { id: 'progress',     slug: 'progress',     label: 'Progress',     icon: '📊' },
  { id: 'phase-trace',  slug: 'phase-trace',  label: 'Phase Trace',  icon: '🔬' },
  { id: 'graph',        slug: 'graph',        label: 'Graph',        icon: '🔗' },
  { id: 'settings',     slug: 'settings',     label: 'Settings',     icon: '⚙️' },
  { id: 'constitution', slug: 'constitution', label: 'Constitution', icon: '📜' },
  { id: 'activity',     slug: 'activity',     label: 'Activity Log', icon: '📝' },
];

const VALID_TABS = new Set(DASH_TABS.map(t => t.slug));

export default function ProjectDashboard() {
  const { projectName, tab } = useParams<{ projectName: string; tab?: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<ProjectData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());

  const activeTab: DashTab = (tab && VALID_TABS.has(tab) ? tab : 'progress') as DashTab;
  const setActiveTab = (t: DashTab) => navigate(`/${encodeURIComponent(projectName ?? '')}/${t}`, { replace: true });

  const load = useCallback(async () => {
    try {
      const res = await fetch(`/api/project-live?name=${encodeURIComponent(projectName ?? '')}`);
      if (!res.ok) {
        const d = await res.json() as { error?: string };
        setError(d.error ?? 'Not found');
        return;
      }
      setData(await res.json() as ProjectData);
      setLastRefresh(new Date());
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [projectName]);

  useEffect(() => {
    load();
    const interval = setInterval(load, 15_000); // refresh every 15s
    return () => clearInterval(interval);
  }, [load]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-slate-100 text-slate-500 text-sm">
        Loading project data…
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex flex-col items-center justify-center h-screen bg-slate-100 gap-4">
        <div className="text-lg font-semibold text-slate-700">Project not found: <code>{projectName}</code></div>
        <div className="text-sm text-slate-500">{error}</div>
        <div className="text-xs text-slate-400">
          Make sure SPIRAL is running with <code className="bg-slate-100 px-1 rounded">SPIRAL_PROJECT_ROOT</code> set,
          or that spiral.sh registered this project.
        </div>
        <Link to="/" className="mt-2 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700">
          ← Back to SPIRAL UI
        </Link>
      </div>
    );
  }

  const p = data.progress;
  const donePct = p ? pct(p.done, p.total) : 0;

  // Determine RUNNING status from multiple signals
  const isRunning = (() => {
    const TWO_MIN = 120_000;
    // Check progress history snapshots
    if (data.progressHistory.length > 0) {
      const lastTs = new Date(data.progressHistory[data.progressHistory.length - 1].ts).getTime();
      if (Date.now() - lastTs < TWO_MIN) return true;
    }
    // Check checkpoint timestamp
    if (data.checkpointTs) {
      if (Date.now() - new Date(data.checkpointTs).getTime() < TWO_MIN) return true;
    }
    // Check log file modification time
    if (data.lastLogModified) {
      if (Date.now() - new Date(data.lastLogModified).getTime() < TWO_MIN) return true;
    }
    return false;
  })();

  const statusTooltip = isRunning
    ? 'RUNNING: SPIRAL log or checkpoint was updated within the last 2 minutes, indicating an active loop.'
    : 'IDLE: No log, checkpoint, or progress updates detected in the last 2 minutes. SPIRAL may have finished or not started yet.';

  return (
    <div className="flex flex-col h-screen bg-slate-100 overflow-hidden">
      {/* Header */}
      <header className="flex items-center gap-4 px-5 py-2.5 bg-white border-b border-slate-200 shadow-sm flex-shrink-0">
        <Link to="/" className="text-slate-400 hover:text-slate-600 text-sm mr-1">← SPIRAL</Link>
        <div className="h-4 w-px bg-slate-200" />

        <div className="flex items-center gap-2">
          <span className="text-lg font-bold text-slate-800">{data.progress?.productName ?? data.name}</span>
          <span
            className={`px-2 py-0.5 rounded-full text-[10px] font-bold cursor-help ${
              isRunning ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'
            }`}
            title={statusTooltip}
          >
            {isRunning ? '● RUNNING' : '○ IDLE'}
          </span>
        </div>

        {p && (
          <div className="flex items-center gap-3 ml-4">
            <div className="w-32 h-2 rounded-full bg-slate-200 overflow-hidden">
              <div className="h-full rounded-full bg-emerald-500" style={{ width: `${donePct}%` }} />
            </div>
            <span className="text-xs text-slate-600 font-medium">{donePct}% · {p.done}/{p.total}</span>
          </div>
        )}

        <div className="ml-auto flex items-center gap-3">
          <span className="text-xs text-slate-400">↻ {timeAgo(lastRefresh.toISOString())}</span>
          <button
            onClick={() => load()}
            className="px-2.5 py-1 text-xs rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-600"
          >
            Refresh
          </button>
        </div>
      </header>

      {/* Project path + overview */}
      {(data.root || p?.overview) && (
        <div className="px-5 py-2 bg-blue-50 border-b border-blue-100 flex-shrink-0">
          {p?.overview && <p className="text-xs text-blue-700 leading-snug">{p.overview}</p>}
          <p className="text-[10px] text-blue-400 mt-0.5 font-mono">{data.root}</p>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 px-5 pt-3 pb-0 bg-white border-b border-slate-200 flex-shrink-0">
        {DASH_TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-1.5 px-3 py-2 text-sm font-medium rounded-t-lg border-b-2 transition-colors ${
              activeTab === tab.id
                ? 'border-blue-600 text-blue-700 bg-blue-50'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            <span>{tab.icon}</span>{tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <main className="flex-1 overflow-hidden">
        {activeTab === 'progress'     && <div className="h-full overflow-y-auto"><ProgressTab data={data} /></div>}
        {activeTab === 'phase-trace'  && <div className="h-full overflow-y-auto"><PhaseTraceTab projectName={projectName ?? ''} /></div>}
        {activeTab === 'graph'        && (
          <div className="h-full overflow-hidden">
            <DependencyGraph stories={data.progress?.stories ?? []} />
          </div>
        )}
        {activeTab === 'settings'     && <div className="h-full overflow-y-auto"><SettingsTab config={data.config} /></div>}
        {activeTab === 'constitution' && <div className="h-full overflow-y-auto"><ConstitutionTab text={data.constitution} /></div>}
        {activeTab === 'activity'     && <div className="h-full overflow-y-auto"><ActivityTab log={data.activity} /></div>}
      </main>
    </div>
  );
}
