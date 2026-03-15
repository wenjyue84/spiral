import { useState, useEffect, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';

// ── Types ────────────────────────────────────────────────────────────────────

interface Story {
  id: string;
  title: string;
  passes: boolean;
  priority?: string;
  complexity?: string;
  failureReason?: string;
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
}

// ── Helpers ──────────────────────────────────────────────────────────────────

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

  const done = p.stories.filter(s => s.passes);
  const pending = p.stories.filter(s => !s.passes);
  const donePct = pct(p.done, p.total);

  return (
    <div className="p-6 space-y-6">
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
                    <td className="px-3 py-1.5 text-slate-400">{timeAgo(snap.ts)}</td>
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
                {s.priority && <span className="text-[10px] text-slate-400">{s.priority}</span>}
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
            {entries.map(([k, v]) => (
              <tr key={k} className="border-t border-slate-100 hover:bg-slate-50">
                <td className="px-4 py-2 font-mono text-blue-700 whitespace-nowrap">{k}</td>
                <td className="px-4 py-2 font-mono text-slate-700 break-all">{v}</td>
              </tr>
            ))}
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

function ActivityTab({ log }: { log: string }) {
  if (!log) {
    return <div className="p-6 text-slate-500">No activity log yet. Start SPIRAL to see live output here.</div>;
  }
  const lines = log.split('\n').filter(Boolean);
  return (
    <div className="p-6">
      <div className="rounded-xl bg-slate-950 overflow-auto max-h-[600px]">
        <pre className="p-4 text-[11px] text-slate-300 font-mono leading-relaxed whitespace-pre-wrap">
          {lines.join('\n')}
        </pre>
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

type DashTab = 'progress' | 'settings' | 'constitution' | 'activity';

const DASH_TABS: { id: DashTab; label: string; icon: string }[] = [
  { id: 'progress',     label: 'Progress',     icon: '📊' },
  { id: 'settings',     label: 'Settings',     icon: '⚙️' },
  { id: 'constitution', label: 'Constitution', icon: '📜' },
  { id: 'activity',     label: 'Activity Log', icon: '📝' },
];

export default function ProjectDashboard() {
  const { projectName } = useParams<{ projectName: string }>();
  const [data, setData] = useState<ProjectData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [activeTab, setActiveTab] = useState<DashTab>('progress');

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
  const isRunning = data.progressHistory.length > 0 &&
    (Date.now() - new Date(data.progressHistory[data.progressHistory.length - 1].ts).getTime()) < 120_000;

  return (
    <div className="flex flex-col h-screen bg-slate-100 overflow-hidden">
      {/* Header */}
      <header className="flex items-center gap-4 px-5 py-2.5 bg-white border-b border-slate-200 shadow-sm flex-shrink-0">
        <Link to="/" className="text-slate-400 hover:text-slate-600 text-sm mr-1">← SPIRAL</Link>
        <div className="h-4 w-px bg-slate-200" />

        <div className="flex items-center gap-2">
          <span className="text-lg font-bold text-slate-800">{data.progress?.productName ?? data.name}</span>
          <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
            isRunning ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'
          }`}>
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
      <main className="flex-1 overflow-y-auto">
        {activeTab === 'progress'     && <ProgressTab data={data} />}
        {activeTab === 'settings'     && <SettingsTab config={data.config} />}
        {activeTab === 'constitution' && <ConstitutionTab text={data.constitution} />}
        {activeTab === 'activity'     && <ActivityTab log={data.activity} />}
      </main>
    </div>
  );
}
