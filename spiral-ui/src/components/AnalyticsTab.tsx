import { useState, useEffect, useCallback } from 'react';

// ── Types ────────────────────────────────────────────────────────────────────

interface AnalyticsData {
  overview: {
    totalAttempts: number; estimatedCost: number; elapsed: string;
    iterations: number; passed: number; pending: number;
    decomposed: number; skipped: number; total: number;
  };
  velocity: Array<{ iter: number; kept: number; total: number; durationHours: number; velocityPerHr: number }>;
  modelPerformance: Array<{ model: string; total: number; kept: number; successRate: number; avgDurationSec: number }>;
  retryAnalysis: Array<{ attempt: number; total: number; kept: number; successRate: number }>;
  resourceUsage: Array<{ model: string; count: number; wallP50: number; wallP95: number; rssP50: number; rssP95: number }>;
  bottlenecks: {
    mostRetried: Array<{ id: string; title: string; retries: number }>;
    longest: Array<{ id: string; title: string; durationMin: number }>;
  };
  iterationVelocity: Array<{ iter: number; kept: number }>;
  statusBreakdown: { passed: number; pending: number; decomposed: number; skipped: number };
  tokenForecast: { burnRatePerHour: number; hoursLeft: number; dailyLimit: number } | null;
  qualityScores: Array<{ phase: string; avgScore: number; latest: number; n: number; rationale: string }>;
  epics: Array<{ epicId: string; title: string; total: number; done: number; pct: number }>;
  decomposition: { effectiveness: number; parents: Array<{ id: string; children: Array<{ id: string; passes: boolean }> }> };
  failureReasons: Array<{
    id: string; title: string; reason: string;
    category: 'cost_ceiling' | 'dependency_blocked' | 'too_large' | 'rejected' | 'never_attempted' | 'pending_retry';
    retryCount: number; model: string; source: string; complexity: string;
    priority: string; dependencies: string[]; depsStatus: Array<{ id: string; met: boolean }>;
    lastAttempted: string | null; attemptCount: number;
    lastModel: string | null; lastStatus: string | null; lastDurationSec: number | null;
    scopeCreep: boolean; recommendation: string;
  }>;
  insights: string[];
  latestScreenshot: string | null;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const fmtK = (n: number) => n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1_000 ? `${(n / 1_000).toFixed(1)}K` : String(n);

// ── Component ────────────────────────────────────────────────────────────────

export default function AnalyticsTab({ projectName }: { projectName: string }) {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch(`/api/analytics?name=${encodeURIComponent(projectName)}`);
      if (!res.ok) {
        const d = await res.json() as { error?: string };
        setError(d.error ?? 'Failed to load analytics');
        return;
      }
      setData(await res.json() as AnalyticsData);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [projectName]);

  useEffect(() => {
    load();
    const interval = setInterval(load, 30_000);
    return () => clearInterval(interval);
  }, [load]);

  if (loading) return <div className="p-6 text-sm text-slate-500">Loading analytics...</div>;
  if (error) return <div className="p-6 text-sm text-red-500">Error: {error}</div>;
  if (!data) return <div className="p-6 text-sm text-slate-400">No analytics data available</div>;

  const { overview: ov, statusBreakdown: sb, insights, velocity, modelPerformance, retryAnalysis,
    resourceUsage, bottlenecks, iterationVelocity, qualityScores, tokenForecast,
    epics, decomposition, failureReasons, latestScreenshot } = data;

  const hasData = ov.totalAttempts > 0;
  if (!hasData) {
    return (
      <div className="p-6 flex flex-col items-center justify-center gap-3 text-center">
        <div className="text-3xl">📈</div>
        <div className="text-sm font-medium text-slate-600">No analytics data yet</div>
        <div className="text-xs text-slate-400 max-w-sm">
          Analytics are computed from results.tsv after SPIRAL runs. Start SPIRAL to begin tracking.
        </div>
      </div>
    );
  }

  // Stacked bar percentages
  const sbTotal = sb.passed + sb.pending + sb.decomposed + sb.skipped || 1;
  const sbPct = (n: number) => `${Math.round((n / sbTotal) * 100)}%`;

  // Velocity chart: compute max for bar heights
  const maxKept = Math.max(1, ...iterationVelocity.map(v => v.kept));

  return (
    <div className="p-6 space-y-6">

      {/* ── 1. Overview Cards ─────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
          <div className="text-2xl font-bold text-blue-700">{ov.totalAttempts}</div>
          <div className="text-xs text-blue-600 mt-0.5">Total Attempts</div>
        </div>
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
          <div className="text-2xl font-bold text-emerald-700">${ov.estimatedCost.toFixed(2)}</div>
          <div className="text-xs text-emerald-600 mt-0.5">Estimated Cost</div>
        </div>
        <div className="rounded-xl border border-violet-200 bg-violet-50 p-4">
          <div className="text-2xl font-bold text-violet-700">{ov.elapsed}</div>
          <div className="text-xs text-violet-600 mt-0.5">Elapsed</div>
          <div className="text-[10px] text-violet-400 mt-0.5">{ov.iterations} iteration{ov.iterations !== 1 ? 's' : ''}</div>
        </div>
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
          <div className="text-2xl font-bold text-amber-700">
            {velocity.length > 0 ? velocity[velocity.length - 1].velocityPerHr : 0}
          </div>
          <div className="text-xs text-amber-600 mt-0.5">Stories/hr (latest)</div>
        </div>
      </div>

      {/* ── 2. Blocked Stories & Failure Analysis (top priority) ──────────── */}
      {failureReasons.length > 0 && (() => {
        const catLabel: Record<string, string> = {
          cost_ceiling: 'Cost Ceiling Hit', too_large: 'Too Large / Decompose',
          dependency_blocked: 'Dependency Blocked', rejected: 'Rejected (will retry)',
          pending_retry: 'Pending Retry', never_attempted: 'Not Yet Attempted',
        };
        const catColor: Record<string, { border: string; bg: string; text: string; badge: string }> = {
          cost_ceiling:       { border: 'border-red-300',    bg: 'bg-red-50',    text: 'text-red-800',    badge: 'bg-red-100 text-red-700' },
          too_large:          { border: 'border-orange-300', bg: 'bg-orange-50', text: 'text-orange-800', badge: 'bg-orange-100 text-orange-700' },
          dependency_blocked: { border: 'border-amber-300',  bg: 'bg-amber-50',  text: 'text-amber-800',  badge: 'bg-amber-100 text-amber-700' },
          rejected:           { border: 'border-rose-200',   bg: 'bg-rose-50',   text: 'text-rose-700',   badge: 'bg-rose-100 text-rose-600' },
          pending_retry:      { border: 'border-violet-200', bg: 'bg-violet-50', text: 'text-violet-700', badge: 'bg-violet-100 text-violet-600' },
          never_attempted:    { border: 'border-slate-200',  bg: 'bg-slate-50',  text: 'text-slate-600',  badge: 'bg-slate-100 text-slate-500' },
        };
        // Group by category
        const grouped = new Map<string, typeof failureReasons>();
        for (const f of failureReasons) {
          if (!grouped.has(f.category)) grouped.set(f.category, []);
          grouped.get(f.category)!.push(f);
        }
        const catOrder = ['cost_ceiling', 'too_large', 'dependency_blocked', 'rejected', 'pending_retry', 'never_attempted'];
        const actionableCount = failureReasons.filter(f => f.category !== 'never_attempted').length;
        const fmtAgo = (ts: string | null): string => {
          if (!ts) return 'never';
          const ms = Date.now() - new Date(ts).getTime();
          const h = Math.floor(ms / 3600000);
          if (h < 1) return `${Math.floor(ms / 60000)}m ago`;
          if (h < 24) return `${h}h ago`;
          return `${Math.floor(h / 24)}d ago`;
        };
        return (
          <div>
            <div className="flex items-center justify-between mb-3">
              <div className="text-xs font-medium text-slate-500 uppercase tracking-wide">
                Blocked Stories ({failureReasons.length})
                {actionableCount > 0 && <span className="ml-2 text-red-500 normal-case">{actionableCount} need attention</span>}
              </div>
              <div className="flex gap-2 text-[10px]">
                {catOrder.filter(c => grouped.has(c)).map(c => {
                  const colors = catColor[c];
                  return (
                    <span key={c} className={`px-2 py-0.5 rounded-full ${colors.badge}`}>
                      {catLabel[c]} ({grouped.get(c)!.length})
                    </span>
                  );
                })}
              </div>
            </div>

            <div className="space-y-3">
              {catOrder.filter(c => grouped.has(c)).map(cat => {
                const items = grouped.get(cat)!;
                const colors = catColor[cat];
                return (
                  <div key={cat} className={`rounded-lg border ${colors.border} ${colors.bg} overflow-hidden`}>
                    <div className={`px-4 py-2 text-xs font-semibold ${colors.text} border-b ${colors.border} flex items-center justify-between`}>
                      <span>{catLabel[cat]}</span>
                      <span className="font-normal opacity-70">{items.length} {items.length === 1 ? 'story' : 'stories'}</span>
                    </div>
                    <div className="divide-y divide-slate-100/50">
                      {items.map(f => (
                        <div key={f.id} className="px-4 py-3">
                          <div className="flex items-start justify-between gap-3">
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 mb-1">
                                <span className="font-mono text-xs font-bold text-slate-700">{f.id}</span>
                                <span className={`text-[10px] px-1.5 py-0.5 rounded ${f.priority === 'high' ? 'bg-red-100 text-red-600' : f.priority === 'medium' ? 'bg-amber-100 text-amber-600' : 'bg-slate-100 text-slate-500'}`}>
                                  {f.priority || '?'}
                                </span>
                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">{f.source || '?'}</span>
                                {f.complexity && <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-600">{f.complexity}</span>}
                                {f.scopeCreep && <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-100 text-red-600">scope-creep</span>}
                              </div>
                              <div className="text-xs text-slate-700 mb-1.5 truncate" title={f.title}>{f.title}</div>
                              <div className="text-[11px] text-slate-500 mb-1">{f.reason}</div>
                            </div>
                            <div className="text-right shrink-0 space-y-0.5">
                              <div className="text-[10px] text-slate-500">
                                {f.retryCount > 0 && <span className={`font-bold ${f.retryCount >= 3 ? 'text-red-600' : 'text-slate-600'}`}>{f.retryCount} retries</span>}
                                {f.retryCount === 0 && <span className="text-slate-400">0 retries</span>}
                              </div>
                              <div className="text-[10px] text-slate-400">model: {f.model || '?'}</div>
                              {f.attemptCount > 0 && (
                                <div className="text-[10px] text-slate-400">
                                  {f.attemptCount} attempt{f.attemptCount > 1 ? 's' : ''}
                                  {f.lastDurationSec != null && <span> ({f.lastDurationSec}s)</span>}
                                </div>
                              )}
                              <div className="text-[10px] text-slate-400">{fmtAgo(f.lastAttempted)}</div>
                            </div>
                          </div>
                          {/* Dependencies */}
                          {f.depsStatus.length > 0 && (
                            <div className="flex gap-1.5 mt-1.5 flex-wrap">
                              <span className="text-[10px] text-slate-400">deps:</span>
                              {f.depsStatus.map(d => (
                                <span key={d.id} className={`text-[10px] px-1.5 py-0.5 rounded-full ${d.met ? 'bg-emerald-100 text-emerald-600' : 'bg-red-100 text-red-600 font-medium'}`}>
                                  {d.id} {d.met ? 'pass' : 'UNMET'}
                                </span>
                              ))}
                            </div>
                          )}
                          {/* Recommendation */}
                          <div className="mt-2 text-[11px] text-slate-500 italic bg-white/60 rounded px-2 py-1.5 border border-slate-100">
                            {f.recommendation}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })()}

      {/* ── 3. Story Status Stacked Bar ───────────────────────────────────── */}
      <div>
        <div className="text-xs font-medium text-slate-500 mb-2 uppercase tracking-wide">Story Status</div>
        <div className="flex h-6 rounded-full overflow-hidden border border-slate-200">
          {sb.passed > 0 && <div className="bg-emerald-500" style={{ width: sbPct(sb.passed) }} title={`Passed: ${sb.passed}`} />}
          {sb.pending > 0 && <div className="bg-violet-500" style={{ width: sbPct(sb.pending) }} title={`Pending: ${sb.pending}`} />}
          {sb.decomposed > 0 && <div className="bg-amber-400" style={{ width: sbPct(sb.decomposed) }} title={`Decomposed: ${sb.decomposed}`} />}
          {sb.skipped > 0 && <div className="bg-slate-300" style={{ width: sbPct(sb.skipped) }} title={`Skipped: ${sb.skipped}`} />}
        </div>
        <div className="flex gap-4 mt-1.5 text-[10px] text-slate-500">
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" /> Passed ({sb.passed})</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-violet-500 inline-block" /> Pending ({sb.pending})</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-400 inline-block" /> Decomposed ({sb.decomposed})</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-slate-300 inline-block" /> Skipped ({sb.skipped})</span>
        </div>
      </div>

      {/* ── 3. Insights ───────────────────────────────────────────────────── */}
      {insights.length > 0 && (
        <div className="space-y-2">
          {insights.map((insight, i) => (
            <div key={i} className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              {insight}
            </div>
          ))}
        </div>
      )}

      {/* ── 4. Velocity Trend (Bar Chart) ─────────────────────────────────── */}
      {iterationVelocity.length > 0 && (
        <div>
          <div className="text-xs font-medium text-slate-500 mb-2 uppercase tracking-wide">Iteration Velocity</div>
          <div className="flex items-end gap-1 h-32 border-b border-l border-slate-200 px-2 pb-1">
            {iterationVelocity.map(v => (
              <div key={v.iter} className="flex flex-col items-center flex-1 min-w-0">
                <div className="text-[9px] text-slate-400 mb-0.5">{v.kept > 0 ? v.kept : ''}</div>
                <div
                  className="w-full max-w-[28px] rounded-t bg-violet-500 transition-all"
                  style={{ height: `${Math.max(2, (v.kept / maxKept) * 100)}%` }}
                  title={`Iter ${v.iter}: ${v.kept} kept`}
                />
                <div className="text-[8px] text-slate-400 mt-0.5">i{v.iter}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── 5. Model Performance + Retry Analysis (2-col) ─────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Model Performance */}
        {modelPerformance.length > 0 && (
          <div>
            <div className="text-xs font-medium text-slate-500 mb-2 uppercase tracking-wide">Model Performance</div>
            <div className="rounded-lg border border-slate-200 overflow-hidden">
              <table className="w-full text-xs">
                <thead className="bg-slate-50 text-slate-500">
                  <tr>
                    <th className="text-left px-3 py-2">Model</th>
                    <th className="text-right px-3 py-2">Tries</th>
                    <th className="text-right px-3 py-2">Kept</th>
                    <th className="text-right px-3 py-2">Rate</th>
                    <th className="text-right px-3 py-2">Avg (s)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {modelPerformance.map(m => (
                    <tr key={m.model} className="hover:bg-slate-50">
                      <td className="px-3 py-1.5 font-mono text-slate-700">{m.model}</td>
                      <td className="px-3 py-1.5 text-right text-slate-600">{m.total}</td>
                      <td className="px-3 py-1.5 text-right text-slate-600">{m.kept}</td>
                      <td className="px-3 py-1.5 text-right">
                        <span className={m.successRate >= 70 ? 'text-emerald-600' : m.successRate >= 40 ? 'text-amber-600' : 'text-red-600'}>
                          {m.successRate}%
                        </span>
                      </td>
                      <td className="px-3 py-1.5 text-right text-slate-600">{m.avgDurationSec}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Retry Analysis */}
        {retryAnalysis.length > 0 && (
          <div>
            <div className="text-xs font-medium text-slate-500 mb-2 uppercase tracking-wide">Retry Analysis</div>
            <div className="space-y-2">
              {retryAnalysis.map(r => (
                <div key={r.attempt} className="flex items-center gap-3">
                  <span className="text-xs text-slate-500 w-16 shrink-0">Attempt {r.attempt}</span>
                  <div className="flex-1 h-4 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${r.successRate >= 70 ? 'bg-emerald-500' : r.successRate >= 40 ? 'bg-amber-500' : 'bg-red-500'}`}
                      style={{ width: `${Math.max(2, r.successRate)}%` }}
                    />
                  </div>
                  <span className="text-xs text-slate-600 w-20 text-right">{r.successRate}% ({r.kept}/{r.total})</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── 6. Resource Usage ─────────────────────────────────────────────── */}
      {resourceUsage.length > 0 && (
        <div>
          <div className="text-xs font-medium text-slate-500 mb-2 uppercase tracking-wide">Resource Usage</div>
          <div className="rounded-lg border border-slate-200 overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-slate-500">
                <tr>
                  <th className="text-left px-3 py-2">Model</th>
                  <th className="text-right px-3 py-2">Count</th>
                  <th className="text-right px-3 py-2">Wall p50</th>
                  <th className="text-right px-3 py-2">Wall p95</th>
                  <th className="text-right px-3 py-2">RSS p50</th>
                  <th className="text-right px-3 py-2">RSS p95</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {resourceUsage.map(r => (
                  <tr key={r.model} className="hover:bg-slate-50">
                    <td className="px-3 py-1.5 font-mono text-slate-700">{r.model}</td>
                    <td className="px-3 py-1.5 text-right text-slate-600">{r.count}</td>
                    <td className="px-3 py-1.5 text-right text-slate-600">{r.wallP50}s</td>
                    <td className="px-3 py-1.5 text-right text-slate-600">{r.wallP95}s</td>
                    <td className="px-3 py-1.5 text-right text-slate-600">{fmtK(r.rssP50)} KB</td>
                    <td className="px-3 py-1.5 text-right text-slate-600">{fmtK(r.rssP95)} KB</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── 7. Bottlenecks (2-col) ────────────────────────────────────────── */}
      {(bottlenecks.mostRetried.length > 0 || bottlenecks.longest.length > 0) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {bottlenecks.mostRetried.length > 0 && (
            <div>
              <div className="text-xs font-medium text-slate-500 mb-2 uppercase tracking-wide">Most Retried</div>
              <div className="space-y-1">
                {bottlenecks.mostRetried.map(b => (
                  <div key={b.id} className="flex items-center justify-between rounded-lg border border-red-100 bg-red-50 px-3 py-2">
                    <div className="text-xs">
                      <span className="font-mono text-red-700">{b.id}</span>
                      {b.title && <span className="text-slate-500 ml-1.5">{b.title}</span>}
                    </div>
                    <span className="text-xs font-bold text-red-600">{b.retries}x</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {bottlenecks.longest.length > 0 && (
            <div>
              <div className="text-xs font-medium text-slate-500 mb-2 uppercase tracking-wide">Longest Implementations</div>
              <div className="space-y-1">
                {bottlenecks.longest.map(b => (
                  <div key={b.id} className="flex items-center justify-between rounded-lg border border-orange-100 bg-orange-50 px-3 py-2">
                    <div className="text-xs">
                      <span className="font-mono text-orange-700">{b.id}</span>
                      {b.title && <span className="text-slate-500 ml-1.5">{b.title}</span>}
                    </div>
                    <span className="text-xs font-bold text-orange-600">{b.durationMin}m</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── 8. Quality Scores ─────────────────────────────────────────────── */}
      {qualityScores.length > 0 && (
        <div>
          <div className="text-xs font-medium text-slate-500 mb-2 uppercase tracking-wide">Quality Scores</div>
          <div className="rounded-lg border border-slate-200 overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-slate-500">
                <tr>
                  <th className="text-left px-3 py-2">Phase</th>
                  <th className="text-right px-3 py-2">Avg</th>
                  <th className="text-right px-3 py-2">Latest</th>
                  <th className="text-right px-3 py-2">Samples</th>
                  <th className="text-left px-3 py-2">Rationale</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {qualityScores.map(q => (
                  <tr key={q.phase} className="hover:bg-slate-50">
                    <td className="px-3 py-1.5 font-mono text-slate-700">{q.phase}</td>
                    <td className="px-3 py-1.5 text-right text-slate-600">{q.avgScore.toFixed(1)}</td>
                    <td className="px-3 py-1.5 text-right text-slate-600">{q.latest.toFixed(1)}</td>
                    <td className="px-3 py-1.5 text-right text-slate-600">{q.n}</td>
                    <td className="px-3 py-1.5 text-slate-500 truncate max-w-[200px]" title={q.rationale}>{q.rationale}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── 9. Token Forecast ─────────────────────────────────────────────── */}
      {tokenForecast && (
        <div className={`rounded-xl border p-4 ${tokenForecast.hoursLeft < 2 ? 'border-amber-300 bg-amber-50' : 'border-slate-200 bg-slate-50'}`}>
          <div className="text-xs font-medium text-slate-500 mb-1 uppercase tracking-wide">Token Forecast</div>
          <div className="flex items-center gap-6">
            <div>
              <div className={`text-2xl font-bold ${tokenForecast.hoursLeft < 2 ? 'text-amber-700' : 'text-slate-700'}`}>
                ~{tokenForecast.hoursLeft}h
              </div>
              <div className="text-[10px] text-slate-500">until exhaustion</div>
            </div>
            <div>
              <div className="text-sm font-medium text-slate-700">{fmtK(tokenForecast.burnRatePerHour)} tok/hr</div>
              <div className="text-[10px] text-slate-500">burn rate</div>
            </div>
            <div>
              <div className="text-sm font-medium text-slate-700">{fmtK(tokenForecast.dailyLimit)}</div>
              <div className="text-[10px] text-slate-500">daily limit</div>
            </div>
          </div>
          {tokenForecast.hoursLeft < 2 && (
            <div className="mt-2 text-xs text-amber-700 font-medium">
              Warning: Token budget may be exhausted within 2 hours at current burn rate
            </div>
          )}
        </div>
      )}

      {/* ── 10. Epics Progress ────────────────────────────────────────────── */}
      {epics.length > 0 && (
        <div>
          <div className="text-xs font-medium text-slate-500 mb-2 uppercase tracking-wide">Epics Progress</div>
          <div className="space-y-2">
            {epics.map(e => (
              <div key={e.epicId}>
                <div className="flex items-center justify-between mb-0.5">
                  <span className="text-xs text-slate-700 font-medium">{e.title}</span>
                  <span className="text-[10px] text-slate-500">{e.done}/{e.total} ({e.pct}%)</span>
                </div>
                <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                  <div className="h-full bg-emerald-500 rounded-full" style={{ width: `${e.pct}%` }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── 11. Decomposition Effectiveness ───────────────────────────────── */}
      {decomposition.parents.length > 0 && (
        <div>
          <div className="text-xs font-medium text-slate-500 mb-2 uppercase tracking-wide">
            Decomposition Effectiveness ({decomposition.effectiveness}%)
          </div>
          <div className="space-y-2">
            {decomposition.parents.map(p => (
              <div key={p.id} className="rounded-lg border border-slate-200 px-3 py-2">
                <div className="text-xs font-mono text-slate-600 mb-1">{p.id} (parent)</div>
                <div className="flex gap-1.5 flex-wrap">
                  {p.children.map(c => (
                    <span key={c.id} className={`text-[10px] px-2 py-0.5 rounded-full ${c.passes ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
                      {c.id} {c.passes ? 'pass' : 'pending'}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Failure Reasons moved to top (after overview) ────────────────── */}

      {/* ── 13. Latest Screenshot ─────────────────────────────────────────── */}
      {latestScreenshot && (
        <div>
          <div className="text-xs font-medium text-slate-500 mb-2 uppercase tracking-wide">Latest Screenshot</div>
          <div className="text-center">
            <img
              src={latestScreenshot}
              alt="App screenshot"
              className="max-w-full rounded-lg border border-slate-200 inline-block"
            />
          </div>
        </div>
      )}
    </div>
  );
}
