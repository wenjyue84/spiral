import { useState, useEffect, useCallback } from 'react';
import { type TokenBurnEntry } from './ProjectDashboard';
import { formatMYT } from './StoryDetailPanel';

// ── Token Stats types ─────────────────────────────────────────────────────────

interface TokenStoryRow {
  story_id: string;
  title: string;
  input: number;
  output: number;
  total: number;
  calls: number;
  usd: number;
  model: string;
  model_tier: string;
  status: string;
}

interface TokenModelRow {
  model: string;
  tier: string;
  input: number;
  output: number;
  total: number;
  stories: number;
}

interface TokenPhaseRow {
  phase: string;
  input: number;
  output: number;
  total: number;
}

interface TrendPoint {
  ts: string;
  input: number;
  output: number;
  total: number;
  cumTotal: number;
}

interface RecentStoryCall {
  ts: string;
  model: string;
  tier: string;
  input: number;
  output: number;
  total: number;
}

interface RecentlyCompletedStory {
  story_id: string;
  title: string;
  models: string[];
  input: number;
  output: number;
  total: number;
  usd: number;
  callCount: number;
  lastTs: string;
  calls: RecentStoryCall[];
}

interface TokenStats {
  total: { input: number; output: number; tokens: number; usd: number };
  avgPerStory: number;
  mostExpensive: { story_id: string; title: string; usd: number } | null;
  byModel: TokenModelRow[];
  byStory: TokenStoryRow[];
  byPhase: TokenPhaseRow[];
  trend: TrendPoint[];
  recentlyCompleted?: RecentlyCompletedStory[];
}

// ── TokenTab component ────────────────────────────────────────────────────────

function fmtK(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function fmtUsd(n: number): string {
  if (n === 0) return '—';
  if (n < 0.001) return '<$0.001';
  return `$${n.toFixed(3)}`;
}

const MODEL_TIER_STYLE: Record<string, string> = {
  haiku:   'bg-sky-100 text-sky-700 border-sky-200',
  sonnet:  'bg-violet-100 text-violet-700 border-violet-200',
  opus:    'bg-amber-100 text-amber-700 border-amber-200',
  unknown: 'bg-slate-100 text-slate-500 border-slate-200',
};

const PHASE_COLORS: Record<string, { bg: string; border: string; text: string; dot: string }> = {
  '0': { bg: 'bg-slate-50',   border: 'border-slate-300',   text: 'text-slate-700',   dot: 'bg-slate-500' },
  A:   { bg: 'bg-indigo-50',  border: 'border-indigo-200',  text: 'text-indigo-700',  dot: 'bg-indigo-500' },
  R:   { bg: 'bg-blue-50',    border: 'border-blue-200',    text: 'text-blue-700',    dot: 'bg-blue-500' },
  T:   { bg: 'bg-violet-50',  border: 'border-violet-200',  text: 'text-violet-700',  dot: 'bg-violet-500' },
  S:   { bg: 'bg-cyan-50',    border: 'border-cyan-200',    text: 'text-cyan-700',    dot: 'bg-cyan-500' },
  E:   { bg: 'bg-sky-50',     border: 'border-sky-200',     text: 'text-sky-700',     dot: 'bg-sky-500' },
  M:   { bg: 'bg-amber-50',   border: 'border-amber-200',   text: 'text-amber-700',   dot: 'bg-amber-500' },
  X:   { bg: 'bg-lime-50',    border: 'border-lime-200',    text: 'text-lime-700',    dot: 'bg-lime-500' },
  I:   { bg: 'bg-emerald-50', border: 'border-emerald-200', text: 'text-emerald-700', dot: 'bg-emerald-500' },
  V:   { bg: 'bg-teal-50',    border: 'border-teal-200',    text: 'text-teal-700',    dot: 'bg-teal-500' },
  P:   { bg: 'bg-purple-50',  border: 'border-purple-200',  text: 'text-purple-700',  dot: 'bg-purple-500' },
  C:   { bg: 'bg-rose-50',    border: 'border-rose-200',    text: 'text-rose-700',    dot: 'bg-rose-500' },
  L:   { bg: 'bg-fuchsia-50', border: 'border-fuchsia-200', text: 'text-fuchsia-700', dot: 'bg-fuchsia-500' },
  D:   { bg: 'bg-orange-50',  border: 'border-orange-200',  text: 'text-orange-700',  dot: 'bg-orange-500' },
};

const PHASE_FULL_NAMES: Record<string, string> = {
  '0': 'Clarify', A: 'AI Suggestions', R: 'Research', T: 'Test Synthesis',
  S: 'Story Validate', E: 'Enrichment', M: 'Merge', X: 'Context Build', I: 'Implement', V: 'Validate',
  P: 'Push', C: 'Check Done', D: 'Loop Decision',
};

export default function TokenTab({ projectName, tokenBurn }: { projectName: string; tokenBurn?: TokenBurnEntry[] }) {
  const [stats, setStats] = useState<TokenStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [tipsOpen, setTipsOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await fetch(`/api/token-stats?name=${encodeURIComponent(projectName)}`);
      if (!res.ok) {
        const d = await res.json() as { error?: string };
        setFetchError(d.error ?? 'Failed to load token stats');
        return;
      }
      setStats(await res.json() as TokenStats);
      setFetchError(null);
    } catch (e) {
      setFetchError(String(e));
    } finally {
      setLoading(false);
    }
  }, [projectName]);

  useEffect(() => {
    load();
    const interval = setInterval(load, 30_000);
    return () => clearInterval(interval);
  }, [load]);

  if (loading) return <div className="p-6 text-sm text-slate-500">Loading token stats…</div>;
  if (fetchError) return <div className="p-6 text-sm text-red-500">Error: {fetchError}</div>;

  const hasData = stats && (stats.total.tokens > 0 || stats.byStory.length > 0);
  if (!hasData) {
    return (
      <div className="p-6 flex flex-col items-center justify-center gap-3 text-center">
        <div className="text-3xl">💰</div>
        <div className="text-sm font-medium text-slate-600">No token data yet</div>
        <div className="text-xs text-slate-400 max-w-sm">
          Token metrics are recorded after each Phase I (Implement) run. Start SPIRAL to begin tracking usage.
        </div>
      </div>
    );
  }

  const s = stats!;

  // Sorted phase data
  const sortedPhases = [...s.byPhase].sort((a, b) => b.total - a.total);
  const maxPhaseTotal = sortedPhases[0]?.total ?? 1;

  // Sorted model data
  const sortedModels = [...s.byModel].sort((a, b) => b.total - a.total);
  const maxModelTotal = sortedModels[0]?.total ?? 1;

  // Optimization tips based on actual data
  const opusPct = (() => {
    const opusRow = s.byModel.find(m => m.tier === 'opus');
    if (!opusRow || s.total.tokens === 0) return 0;
    return Math.round((opusRow.total / s.total.tokens) * 100);
  })();

  const researchPct = (() => {
    const rRow = s.byPhase.find(p => p.phase === 'R');
    if (!rRow || s.total.tokens === 0) return 0;
    return Math.round((rRow.total / s.total.tokens) * 100);
  })();

  const avgUsd = s.total.usd > 0 && s.byStory.length > 0
    ? s.total.usd / s.byStory.length
    : 0;

  // Trend: downsample to ~20 points for display
  const trendDownsampled = (() => {
    const pts = s.trend;
    if (pts.length <= 20) return pts;
    const step = Math.floor(pts.length / 20);
    return pts.filter((_, i) => i % step === 0 || i === pts.length - 1);
  })();
  const maxCumTotal = trendDownsampled[trendDownsampled.length - 1]?.cumTotal ?? 1;

  return (
    <div className="p-6 space-y-6">

      {/* ── A) Summary Cards ─────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="rounded-xl border border-violet-200 bg-violet-50 p-4">
          <div className="text-2xl font-bold text-violet-700">{fmtK(s.total.tokens)}</div>
          <div className="text-xs text-violet-600 mt-0.5">Total Tokens</div>
          <div className="text-[10px] text-violet-400 mt-0.5">{fmtK(s.total.input)} in · {fmtK(s.total.output)} out</div>
        </div>
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
          <div className="text-2xl font-bold text-emerald-700">{fmtUsd(s.total.usd)}</div>
          <div className="text-xs text-emerald-600 mt-0.5">Estimated Cost</div>
          <div className="text-[10px] text-emerald-400 mt-0.5">across all stories</div>
        </div>
        <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
          <div className="text-2xl font-bold text-blue-700">{fmtK(s.avgPerStory)}</div>
          <div className="text-xs text-blue-600 mt-0.5">Avg per Story</div>
          <div className="text-[10px] text-blue-400 mt-0.5">{s.byStory.length} stories tracked</div>
        </div>
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
          <div className="text-lg font-bold text-amber-700 truncate" title={s.mostExpensive?.story_id ?? '—'}>
            {s.mostExpensive?.story_id ?? '—'}
          </div>
          <div className="text-xs text-amber-600 mt-0.5">Most Expensive</div>
          <div className="text-[10px] text-amber-400 mt-0.5">{fmtUsd(s.mostExpensive?.usd ?? 0)}</div>
        </div>
      </div>

      {/* ── A2) Recently Completed Stories ─────────────────────────────── */}
      {s.recentlyCompleted && s.recentlyCompleted.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
            Recently Completed Stories
            <span className="ml-2 text-[10px] font-normal text-slate-400">
              (newest first — {s.recentlyCompleted.length} stories)
            </span>
          </div>
          <div className="space-y-2">
            {s.recentlyCompleted.map(rc => {
              const maxCallTotal = Math.max(1, ...rc.calls.map(c => c.total));
              return (
                <div key={rc.story_id} className="rounded-xl border border-slate-200 bg-white overflow-hidden">
                  {/* Story header */}
                  <div className="flex items-center justify-between px-4 py-3 bg-gradient-to-r from-emerald-50 to-white border-b border-slate-100">
                    <div className="flex items-center gap-3 min-w-0">
                      <span className="font-mono text-sm font-bold text-emerald-700">{rc.story_id}</span>
                      <span className="text-xs text-slate-600 truncate" title={rc.title}>{rc.title}</span>
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0 ml-3">
                      {rc.models.map(m => (
                        <span key={m} className={`inline-block text-[10px] px-2 py-0.5 rounded-full border font-medium ${MODEL_TIER_STYLE[m] ?? MODEL_TIER_STYLE['unknown']}`}>
                          {m}
                        </span>
                      ))}
                      <span className="text-[10px] text-slate-400 ml-1">
                        {new Date(rc.lastTs).toLocaleString([], { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                      </span>
                    </div>
                  </div>

                  {/* Token summary row */}
                  <div className="grid grid-cols-5 gap-3 px-4 py-2.5 text-xs bg-slate-50/50">
                    <div>
                      <div className="text-[10px] text-slate-400 uppercase">Input</div>
                      <div className="font-semibold text-slate-700">{fmtK(rc.input)}</div>
                    </div>
                    <div>
                      <div className="text-[10px] text-slate-400 uppercase">Output</div>
                      <div className="font-semibold text-slate-700">{fmtK(rc.output)}</div>
                    </div>
                    <div>
                      <div className="text-[10px] text-slate-400 uppercase">Total</div>
                      <div className="font-bold text-violet-700">{fmtK(rc.total)}</div>
                    </div>
                    <div>
                      <div className="text-[10px] text-slate-400 uppercase">Cost</div>
                      <div className="font-semibold text-emerald-700">{fmtUsd(rc.usd)}</div>
                    </div>
                    <div>
                      <div className="text-[10px] text-slate-400 uppercase">API Calls</div>
                      <div className="font-semibold text-slate-700">{rc.callCount}</div>
                    </div>
                  </div>

                  {/* Per-call breakdown table */}
                  {rc.calls.length > 0 && (
                    <div className="overflow-x-auto">
                      <table className="w-full text-[11px]">
                        <thead className="bg-slate-50 text-slate-400">
                          <tr>
                            <th className="text-left px-3 py-1.5 font-medium">Time</th>
                            <th className="text-left px-3 py-1.5 font-medium">Model</th>
                            <th className="text-right px-3 py-1.5 font-medium">Input</th>
                            <th className="text-right px-3 py-1.5 font-medium">Output</th>
                            <th className="text-right px-3 py-1.5 font-medium">Total</th>
                            <th className="px-3 py-1.5 w-24 font-medium">Share</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-50">
                          {rc.calls.map((c, i) => {
                            const callPct = maxCallTotal > 0 ? Math.round((c.total / maxCallTotal) * 100) : 0;
                            return (
                              <tr key={i} className="hover:bg-slate-50">
                                <td className="px-3 py-1 text-slate-400 whitespace-nowrap">
                                  {c.ts ? new Date(c.ts).toLocaleString([], { hour: '2-digit', minute: '2-digit' }) : '-'}
                                </td>
                                <td className="px-3 py-1">
                                  <span className={`inline-block text-[10px] px-1.5 py-0.5 rounded-full border font-medium ${MODEL_TIER_STYLE[c.tier] ?? MODEL_TIER_STYLE['unknown']}`}>
                                    {c.tier}
                                  </span>
                                </td>
                                <td className="px-3 py-1 text-right text-slate-500">{fmtK(c.input)}</td>
                                <td className="px-3 py-1 text-right text-slate-500">{fmtK(c.output)}</td>
                                <td className="px-3 py-1 text-right font-medium text-slate-700">{fmtK(c.total)}</td>
                                <td className="px-3 py-1">
                                  <div className="flex items-center gap-1">
                                    <div className="flex-1 h-1.5 rounded-full bg-slate-100 overflow-hidden">
                                      <div className={`h-full rounded-full ${
                                        c.tier === 'haiku' ? 'bg-sky-400' :
                                        c.tier === 'sonnet' ? 'bg-violet-500' :
                                        c.tier === 'opus' ? 'bg-amber-500' : 'bg-slate-400'
                                      }`} style={{ width: `${callPct}%` }} />
                                    </div>
                                  </div>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── B) Model Breakdown ───────────────────────────────────────────── */}
      {sortedModels.length > 0 && (
        <div data-testid="model-heatmap">
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Token Breakdown by Model</div>
          <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-slate-500">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">Model</th>
                  <th className="px-3 py-2 text-right font-medium">Input</th>
                  <th className="px-3 py-2 text-right font-medium">Output</th>
                  <th className="px-3 py-2 text-right font-medium">Total</th>
                  <th className="px-3 py-2 text-right font-medium">Calls</th>
                  <th className="px-3 py-2 w-36 font-medium">Share</th>
                </tr>
              </thead>
              <tbody>
                {sortedModels.map(m => {
                  const share = maxModelTotal > 0 ? Math.round((m.total / maxModelTotal) * 100) : 0;
                  const tierStyle = MODEL_TIER_STYLE[m.tier] ?? MODEL_TIER_STYLE['unknown'];
                  return (
                    <tr key={m.model} className="border-t border-slate-100 hover:bg-slate-50">
                      <td className="px-3 py-2">
                        <span className={`inline-block text-[10px] px-2 py-0.5 rounded-full border font-medium ${tierStyle}`}>
                          {m.tier !== 'unknown' ? m.tier : m.model}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right text-slate-500">{fmtK(m.input)}</td>
                      <td className="px-3 py-2 text-right text-slate-500">{fmtK(m.output)}</td>
                      <td className="px-3 py-2 text-right font-medium text-slate-700">{fmtK(m.total)}</td>
                      <td className="px-3 py-2 text-right text-slate-400">{m.stories}</td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-1.5">
                          <div className="flex-1 h-2 rounded-full bg-slate-100 overflow-hidden">
                            <div
                              className={`h-full rounded-full ${
                                m.tier === 'haiku' ? 'bg-sky-400' :
                                m.tier === 'sonnet' ? 'bg-violet-500' :
                                m.tier === 'opus' ? 'bg-amber-500' : 'bg-slate-400'
                              }`}
                              style={{ width: `${share}%` }}
                            />
                          </div>
                          <span className="text-[10px] text-slate-400 w-7 text-right">{share}%</span>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Phase Breakdown ──────────────────────────────────────────────── */}
      {sortedPhases.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Token Breakdown by Phase</div>
          <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-slate-500">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">Phase</th>
                  <th className="px-3 py-2 text-right font-medium">Input</th>
                  <th className="px-3 py-2 text-right font-medium">Output</th>
                  <th className="px-3 py-2 text-right font-medium">Total</th>
                  <th className="px-3 py-2 w-36 font-medium">Share</th>
                </tr>
              </thead>
              <tbody>
                {sortedPhases.map(p => {
                  const share = maxPhaseTotal > 0 ? Math.round((p.total / maxPhaseTotal) * 100) : 0;
                  const phaseColor = PHASE_COLORS[p.phase];
                  return (
                    <tr key={p.phase} className="border-t border-slate-100 hover:bg-slate-50">
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          {phaseColor && <span className={`w-2 h-2 rounded-full ${phaseColor.dot} flex-shrink-0`} />}
                          <span className="font-mono font-semibold text-slate-700">{p.phase}</span>
                          <span className="text-slate-400">{PHASE_FULL_NAMES[p.phase] ?? p.phase}</span>
                        </div>
                      </td>
                      <td className="px-3 py-2 text-right text-slate-500">{fmtK(p.input)}</td>
                      <td className="px-3 py-2 text-right text-slate-500">{fmtK(p.output)}</td>
                      <td className="px-3 py-2 text-right font-medium text-slate-700">{fmtK(p.total)}</td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-1.5">
                          <div className="flex-1 h-2 rounded-full bg-slate-100 overflow-hidden">
                            <div
                              className={`h-full rounded-full ${phaseColor?.dot.replace('bg-', 'bg-') ?? 'bg-slate-400'}`}
                              style={{ width: `${share}%` }}
                            />
                          </div>
                          <span className="text-[10px] text-slate-400 w-7 text-right">{share}%</span>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── C) Top Token Consumers ───────────────────────────────────────── */}
      {s.byStory.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Top Token Consumers</div>
          <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-slate-500">
                <tr>
                  <th className="px-3 py-2 text-left font-medium w-24">Story</th>
                  <th className="px-3 py-2 text-left font-medium">Model</th>
                  <th className="px-3 py-2 text-right font-medium">Input</th>
                  <th className="px-3 py-2 text-right font-medium">Output</th>
                  <th className="px-3 py-2 text-right font-medium">Total</th>
                  <th className="px-3 py-2 text-right font-medium">Cost</th>
                  <th className="px-3 py-2 text-left font-medium w-20">Status</th>
                  <th className="px-3 py-2 w-28 font-medium">Burn</th>
                </tr>
              </thead>
              <tbody>
                {s.byStory.map(row => {
                  const maxTotal = s.byStory[0]?.total ?? 1;
                  const barPct = maxTotal > 0 ? Math.round((row.total / maxTotal) * 100) : 0;
                  const tierStyle = MODEL_TIER_STYLE[row.model_tier] ?? MODEL_TIER_STYLE['unknown'];
                  const statusBadge = row.status === 'pass'
                    ? 'bg-emerald-100 text-emerald-700'
                    : row.status === 'reject'
                    ? 'bg-red-100 text-red-700'
                    : 'bg-slate-100 text-slate-500';
                  const truncTitle = row.title.length > 50 ? row.title.slice(0, 50) + '…' : row.title;
                  return (
                    <tr key={row.story_id} className="border-t border-slate-100 hover:bg-slate-50">
                      <td className="px-3 py-2">
                        <span className="font-mono font-semibold text-blue-700" title={row.title}>
                          {row.story_id}
                        </span>
                        {row.title && (
                          <div className="text-[10px] text-slate-400 truncate max-w-[140px]" title={row.title}>{truncTitle}</div>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        {row.model_tier !== 'unknown' && (
                          <span className={`inline-block text-[10px] px-1.5 py-0.5 rounded-full border font-medium ${tierStyle}`}>
                            {row.model_tier}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right text-slate-500">{fmtK(row.input)}</td>
                      <td className="px-3 py-2 text-right text-slate-500">{fmtK(row.output)}</td>
                      <td className="px-3 py-2 text-right font-medium text-slate-700">{fmtK(row.total)}</td>
                      <td className="px-3 py-2 text-right text-slate-500">{fmtUsd(row.usd)}</td>
                      <td className="px-3 py-2">
                        {row.status !== 'unknown' && (
                          <span className={`inline-block text-[10px] px-1.5 py-0.5 rounded-full font-medium ${statusBadge}`}>
                            {row.status}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-1.5">
                          <div className="flex-1 h-2 rounded-full bg-slate-100 overflow-hidden">
                            <div className="h-full rounded-full bg-violet-500" style={{ width: `${barPct}%` }} />
                          </div>
                          <span className="text-[10px] text-slate-400 w-7 text-right">{barPct}%</span>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── D) Token Trend Over Time ─────────────────────────────────────── */}
      {trendDownsampled.length > 1 && (
        <div>
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Cumulative Token Spend</div>
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="flex items-end gap-0.5 h-24">
              {trendDownsampled.map((pt, i) => {
                const barH = maxCumTotal > 0 ? Math.round((pt.cumTotal / maxCumTotal) * 100) : 0;
                return (
                  <div
                    key={i}
                    className="flex-1 bg-violet-400 rounded-sm hover:bg-violet-600 transition-colors cursor-default"
                    style={{ height: `${barH}%` }}
                    title={`${formatMYT(pt.ts)}\nCumulative: ${fmtK(pt.cumTotal)} tokens`}
                  />
                );
              })}
            </div>
            <div className="flex justify-between mt-1.5 text-[10px] text-slate-400">
              <span>{trendDownsampled[0] ? formatMYT(trendDownsampled[0].ts) : ''}</span>
              <span>Cumulative: {fmtK(maxCumTotal)} total tokens</span>
              <span>{trendDownsampled[trendDownsampled.length - 1] ? formatMYT(trendDownsampled[trendDownsampled.length - 1].ts) : ''}</span>
            </div>
          </div>
        </div>
      )}

      {/* ── E) Token Burn by Story (from results.tsv, includes cache tokens) ── */}
      {tokenBurn && tokenBurn.length > 0 && (
        <div data-testid="burn-rate">
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Token Burn by Story (detailed)</div>
          <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-slate-500">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">Story</th>
                  <th className="px-3 py-2 text-right font-medium">Input</th>
                  <th className="px-3 py-2 text-right font-medium">Output</th>
                  <th className="px-3 py-2 text-right font-medium">Cache Write</th>
                  <th className="px-3 py-2 text-right font-medium">Cache Read</th>
                  <th className="px-3 py-2 text-right font-medium">Total</th>
                  <th className="px-3 py-2 w-32 font-medium">Burn</th>
                </tr>
              </thead>
              <tbody>
                {[...tokenBurn].sort((a, b) => b.total - a.total).map(e => {
                  const maxTotal = [...tokenBurn].sort((a, b) => b.total - a.total)[0]?.total ?? 1;
                  const barPct = maxTotal > 0 ? Math.round((e.total / maxTotal) * 100) : 0;
                  return (
                    <tr key={e.story_id} className="border-t border-slate-100 hover:bg-slate-50">
                      <td className="px-3 py-1.5 font-mono font-semibold text-blue-700 whitespace-nowrap">{e.story_id}</td>
                      <td className="px-3 py-1.5 text-right text-slate-500">{fmtK(e.input)}</td>
                      <td className="px-3 py-1.5 text-right text-slate-500">{fmtK(e.output)}</td>
                      <td className="px-3 py-1.5 text-right text-slate-400">{fmtK((e as any).creation_tokens)}</td>
                      <td className="px-3 py-1.5 text-right text-emerald-600">{fmtK((e as any).read_tokens)}</td>
                      <td className="px-3 py-1.5 text-right font-medium text-slate-700">{fmtK(e.total)}</td>
                      <td className="px-3 py-1.5">
                        <div className="flex items-center gap-1.5">
                          <div className="flex-1 h-2 rounded-full bg-slate-100 overflow-hidden">
                            <div className="h-full rounded-full bg-violet-500" style={{ width: `${barPct}%` }} />
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
        </div>
      )}

      {/* ── F) Optimization Tips ─────────────────────────────────────────── */}
      <div className="rounded-xl border border-amber-200 bg-amber-50 overflow-hidden">
        <button
          onClick={() => setTipsOpen(v => !v)}
          className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-amber-100/50 transition-colors"
        >
          <span className="text-sm font-semibold text-amber-800">How to save tokens</span>
          <span className={`text-amber-600 text-xs transition-transform ${tipsOpen ? 'rotate-180' : ''}`}>▼</span>
        </button>
        {tipsOpen && (
          <div className="px-4 pb-4 space-y-2 border-t border-amber-200 pt-3">
            {opusPct > 20 && (
              <div className="flex items-start gap-2 text-xs text-amber-800">
                <span className="flex-shrink-0 text-amber-500 font-bold">!</span>
                <span><strong>{opusPct}%</strong> of tokens used opus — consider using sonnet or haiku for simpler stories via <code className="bg-amber-100 px-1 rounded">SPIRAL_MODEL_ROUTING=auto</code></span>
              </div>
            )}
            {researchPct > 30 && (
              <div className="flex items-start gap-2 text-xs text-amber-800">
                <span className="flex-shrink-0 text-amber-500 font-bold">!</span>
                <span><strong>{researchPct}%</strong> of tokens in Research phase — try <code className="bg-amber-100 px-1 rounded">--skip-research</code> for implementation-only runs</span>
              </div>
            )}
            {avgUsd > 1 && (
              <div className="flex items-start gap-2 text-xs text-amber-800">
                <span className="flex-shrink-0 text-amber-500 font-bold">!</span>
                <span>Average story cost is <strong>{fmtUsd(avgUsd)}</strong> — stories over $1.00 are candidates for decomposition via <code className="bg-amber-100 px-1 rounded">SPIRAL_STORY_BATCH_SIZE=1</code></span>
              </div>
            )}
            {s.total.tokens > 100_000 && (
              <div className="flex items-start gap-2 text-xs text-amber-800">
                <span className="flex-shrink-0 text-amber-500 font-bold">!</span>
                <span>Enable prompt caching in your config — check the Progress tab for current cache hit rates</span>
              </div>
            )}
            <div className="flex items-start gap-2 text-xs text-amber-700">
              <span className="flex-shrink-0">•</span>
              <span>Use <code className="bg-amber-100 px-1 rounded">python main.py estimate</code> to project costs before long runs</span>
            </div>
            <div className="flex items-start gap-2 text-xs text-amber-700">
              <span className="flex-shrink-0">•</span>
              <span>Set <code className="bg-amber-100 px-1 rounded">SPIRAL_COST_CEILING</code> to auto-stop when budget is exceeded</span>
            </div>
            <div className="flex items-start gap-2 text-xs text-amber-700">
              <span className="flex-shrink-0">•</span>
              <span>Limit batch size with <code className="bg-amber-100 px-1 rounded">SPIRAL_MAX_PENDING</code> to control how many stories run per iteration</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
