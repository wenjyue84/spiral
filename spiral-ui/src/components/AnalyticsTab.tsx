import { useState, useEffect, useCallback } from 'react';
import { AgentTelemetryTable, PhaseTimingBars, PhaseTimelineChart, StoriesListAccordion, RecentActivityFeed, CollapsibleSection, FailureRetryDashboard, StuckStoriesPanel, CumulativeCostChart, ModelCostDonut } from './analytics';
import StoryDetailPanel, { type StoryForPanel, type StoryAttempt } from './StoryDetailPanel';

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
  resolvedFailures: Array<{
    id: string; title: string; reason: string;
    category: string; retryCount: number; model: string; source: string;
    resolvedAs: 'passed' | 'skipped' | 'decomposed';
  }>;
  prdVelocity: {
    storiesPerHour: number; totalStories: number; elapsedHours: number;
    isProjected: boolean; label: string;
    sessions: Array<{ date: string; stories: number; hours: number; velocity: number }>;
    latestSessionVelocity: number;
  };
  insights: string[];
  latestScreenshot: string | null;
  agentTelemetry: Array<{
    ts: string; workerId: string; storyId: string;
    fromPhase: string; toPhase: string;
    durationMs: number; qualityScore: number; retryCount: number;
  }>;
  phaseTimings: Array<{ phase: string; durationSec: number; label: string }>;
  storiesList: Array<{
    id: string; title: string; passes: boolean;
    _decomposed: boolean; _skipped: boolean; _failureReason: string;
    epicId: string; priority: string; source: string;
    attempts: Array<{
      timestamp: string; model: string; status: string;
      durationSec: number; retryNum: number; commitSha: string;
      runId: string; inputTokens: number; outputTokens: number;
    }>;
  }>;
  storyDetails?: Record<string, StoryForPanel>;
  storyAttempts?: Record<string, StoryAttempt[]>;
  recentActivity?: Array<{ header: string; body: string }>;
  cumulativeTrendData?: Array<{ iter: number; cumulativeCost: number; cumulativePassed: number }>;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const fmtK = (n: number) => n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1_000 ? `${(n / 1_000).toFixed(1)}K` : String(n);

const sliceDataByRange = <T,>(data: T[], range: 'all' | '10' | '20' | '50'): T[] => {
  if (range === 'all') return data;
  const n = parseInt(range, 10);
  return data.slice(Math.max(0, data.length - n));
};

// ── Component ────────────────────────────────────────────────────────────────

export default function AnalyticsTab({ projectName }: { projectName: string }) {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedStoryId, setSelectedStoryId] = useState<string | null>(null);
  const [iterationRangeFilter, setIterationRangeFilter] = useState<'all' | '10' | '20' | '50'>('all');

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

  if (loading) return <div className="p-4 text-sm text-slate-500">Loading analytics...</div>;
  if (error) return <div className="p-4 text-sm text-red-500">Error: {error}</div>;
  if (!data) return <div className="p-4 text-sm text-slate-400">No analytics data available</div>;

  const { overview: ov, statusBreakdown: sb, insights, velocity, retryAnalysis, modelPerformance,
    resourceUsage, bottlenecks, iterationVelocity, qualityScores, tokenForecast,
    epics, decomposition, failureReasons, resolvedFailures, latestScreenshot, prdVelocity,
    agentTelemetry, phaseTimings, storiesList, storyDetails, storyAttempts,
    recentActivity = [], cumulativeTrendData = [] } = data;

  const hasData = ov.totalAttempts > 0 || ov.passed > 0;
  if (!hasData) {
    return (
      <div className="p-4 flex flex-col items-center justify-center gap-3 text-center">
        <div className="text-3xl">📈</div>
        <div className="text-sm font-medium text-slate-600">No analytics data yet</div>
        <div className="text-xs text-slate-400 max-w-sm">
          Analytics are computed from results.tsv after SPIRAL runs. Start SPIRAL to begin tracking.
        </div>
      </div>
    );
  }

  const sbTotal = sb.passed + sb.pending + sb.decomposed + sb.skipped || 1;
  const sbPct = (n: number) => `${Math.round((n / sbTotal) * 100)}%`;
  const velocityValue = prdVelocity.latestSessionVelocity > 0
    ? prdVelocity.latestSessionVelocity
    : velocity.length > 0 ? velocity[velocity.length - 1].velocityPerHr : 0;

  return (
    <div className="p-4 space-y-3">

      {/* ── TIER 1: Status Strip ──────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-3 py-2 rounded-lg bg-slate-50 border border-slate-200 text-xs">
        <span><strong className="text-blue-700">{ov.totalAttempts}</strong> attempts</span>
        <span><strong className="text-emerald-700">${ov.estimatedCost.toFixed(2)}</strong> cost</span>
        <span><strong className="text-violet-700">{ov.elapsed}</strong> <span className="text-slate-400">({ov.iterations} iter)</span></span>
        <span><strong className="text-amber-700">{velocityValue}</strong> stories/hr</span>
        <div className="flex items-center gap-2 ml-auto">
          <div className="flex h-3 w-36 rounded-full overflow-hidden border border-slate-200">
            {sb.passed > 0 && <div className="bg-emerald-500" style={{ width: sbPct(sb.passed) }} title={`Passed: ${sb.passed}`} />}
            {sb.pending > 0 && <div className="bg-violet-500" style={{ width: sbPct(sb.pending) }} title={`Pending: ${sb.pending}`} />}
            {sb.decomposed > 0 && <div className="bg-amber-400" style={{ width: sbPct(sb.decomposed) }} title={`Decomposed: ${sb.decomposed}`} />}
            {sb.skipped > 0 && <div className="bg-slate-300" style={{ width: sbPct(sb.skipped) }} title={`Skipped: ${sb.skipped}`} />}
          </div>
          <span className="text-[10px] text-slate-400">{sb.passed}/{sbTotal}</span>
        </div>
        <div className="w-full flex items-center gap-1">
          <span className="text-[10px] text-slate-400 mr-1">Range:</span>
          {(['all', '10', '20', '50'] as const).map(range => (
            <button
              key={range}
              onClick={() => setIterationRangeFilter(range)}
              className={`text-[10px] px-2 py-1 rounded-full transition-colors ${
                iterationRangeFilter === range
                  ? 'bg-blue-500 text-white'
                  : 'bg-slate-200 text-slate-600 hover:bg-slate-300'
              }`}
            >
              {range === 'all' ? 'All' : `Last ${range}`}
            </button>
          ))}
        </div>
      </div>

      {/* ── TIER 1: Failure & Retry Dashboard ─────────────────────────────── */}
      <FailureRetryDashboard
        failureReasons={failureReasons}
        bottlenecks={bottlenecks}
        modelPerformance={modelPerformance}
        retryAnalysis={retryAnalysis}
        storiesList={storiesList}
        onStoryClick={setSelectedStoryId}
      />

      {/* ── TIER 1: Stuck Stories (retry exhaustion) ─────────────────────── */}
      <StuckStoriesPanel />

      {/* ── TIER 2: Velocity + Phase Timings (side-by-side) ──────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {iterationVelocity.length > 0 && (() => {
          const slicedVelocity = sliceDataByRange(iterationVelocity, iterationRangeFilter);
          const slicedMaxKept = Math.max(1, ...slicedVelocity.map(v => v.kept));
          return (
            <div>
              <div className="text-xs font-medium text-slate-500 mb-1 uppercase tracking-wide">Iteration Velocity</div>
              <div className="flex items-end gap-1 h-28 border-b border-l border-slate-200 px-2 pb-1">
                {slicedVelocity.map(v => (
                  <div key={v.iter} className="flex flex-col items-center flex-1 min-w-0">
                    <div className="text-[9px] text-slate-400 mb-0.5">{v.kept > 0 ? v.kept : ''}</div>
                    <div
                      className="w-full max-w-[28px] rounded-t bg-violet-500 transition-all"
                      style={{ height: `${Math.max(2, (v.kept / slicedMaxKept) * 100)}%` }}
                      title={`Iter ${v.iter}: ${v.kept} kept`}
                    />
                    <div className="text-[8px] text-slate-400 mt-0.5">i{v.iter}</div>
                  </div>
                ))}
              </div>
            </div>
          );
        })()}
        <PhaseTimingBars data={phaseTimings} />
      </div>

      {/* ── TIER 2b: Phase Duration Timeline (bottleneck identification) ──── */}
      {phaseTimings.length > 0 && (
        <PhaseTimelineChart timings={phaseTimings} />
      )}

      {/* ── TIER 2c: Cumulative Cost & Stories Passed Trend Chart ────────── */}
      {cumulativeTrendData.length > 0 && (
        <CumulativeCostChart data={sliceDataByRange(cumulativeTrendData, iterationRangeFilter)} />
      )}

      {/* ── TIER 3: Collapsible sections ──────────────────────────────────── */}

      {insights.length > 0 && (
        <CollapsibleSection title="Insights" badge={insights.length} badgeColor="bg-amber-100 text-amber-700">
          <div className="space-y-1.5">
            {insights.map((insight, i) => (
              <div key={i} className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                {insight}
              </div>
            ))}
          </div>
        </CollapsibleSection>
      )}

      {resolvedFailures.length > 0 && (
        <CollapsibleSection title="Resolved Failures" badge={resolvedFailures.length} badgeColor="bg-emerald-100 text-emerald-700">
          <div className="rounded-lg border border-slate-200 overflow-hidden">
            <table className="w-full text-[11px]">
              <thead className="bg-slate-50 text-slate-500">
                <tr>
                  <th className="text-left px-2 py-1">Story</th>
                  <th className="text-left px-2 py-1">Title</th>
                  <th className="text-left px-2 py-1">Category</th>
                  <th className="text-center px-2 py-1">Retries</th>
                  <th className="text-left px-2 py-1">Resolution</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {resolvedFailures.map(f => (
                  <tr key={f.id} className="hover:bg-slate-50">
                    <td className="px-2 py-1 font-mono text-slate-700">{f.id}</td>
                    <td className="px-2 py-1 text-slate-600 max-w-[200px] truncate" title={f.title}>{f.title}</td>
                    <td className="px-2 py-1">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                        f.category === 'cost_ceiling' ? 'bg-red-100 text-red-600' :
                        f.category === 'too_large' ? 'bg-orange-100 text-orange-600' :
                        f.category === 'dependency_blocked' ? 'bg-amber-100 text-amber-600' :
                        'bg-slate-100 text-slate-500'
                      }`}>
                        {f.category}
                      </span>
                    </td>
                    <td className="px-2 py-1 text-center">
                      <span className={f.retryCount >= 3 ? 'text-red-600 font-bold' : 'text-slate-500'}>{f.retryCount}</span>
                    </td>
                    <td className="px-2 py-1">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                        f.resolvedAs === 'passed' ? 'bg-emerald-100 text-emerald-700' :
                        f.resolvedAs === 'decomposed' ? 'bg-amber-100 text-amber-700' :
                        'bg-slate-100 text-slate-500'
                      }`}>
                        {f.resolvedAs}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CollapsibleSection>
      )}

      {(prdVelocity.sessions.length > 0 || resourceUsage.length > 0) && (
        <CollapsibleSection title="Session Velocity & Resources" badge={prdVelocity.sessions.length > 0 ? `${prdVelocity.storiesPerHour}/hr` : undefined}>
          <div className="space-y-3">
            {prdVelocity.sessions.length > 0 && (() => {
              const maxVel = Math.max(1, ...prdVelocity.sessions.map(s => s.velocity));
              return (
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <div className="text-xs font-medium text-slate-500 uppercase tracking-wide">Session Velocity</div>
                    <div className="text-[10px] text-slate-400">
                      Overall: {prdVelocity.storiesPerHour} stories/hr
                      {prdVelocity.isProjected && ' (projected)'}
                    </div>
                  </div>
                  <div className="flex items-end gap-2 h-28 border-b border-l border-slate-200 px-2 pb-1">
                    {prdVelocity.sessions.map((s, i) => (
                      <div key={i} className="flex flex-col items-center flex-1 min-w-0">
                        <div className="text-[9px] text-slate-400 mb-0.5">{s.velocity > 0 ? s.velocity : ''}</div>
                        <div
                          className={`w-full max-w-[36px] rounded-t transition-all ${
                            i === prdVelocity.sessions.length - 1 && prdVelocity.isProjected
                              ? 'bg-amber-400 bg-opacity-70' : 'bg-emerald-500'
                          }`}
                          style={{ height: `${Math.max(4, (s.velocity / maxVel) * 100)}%` }}
                          title={`${s.stories} stories in ${s.hours}h = ${s.velocity}/hr`}
                        />
                        <div className="text-[8px] text-slate-400 mt-0.5 truncate w-full text-center">{s.date.slice(5)}</div>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })()}
            {resourceUsage.length > 0 && (
              <div>
                <div className="text-xs font-medium text-slate-500 mb-1 uppercase tracking-wide">Resource Usage</div>
                <div className="rounded-lg border border-slate-200 overflow-hidden">
                  <table className="w-full text-[11px]">
                    <thead className="bg-slate-50 text-slate-500">
                      <tr>
                        <th className="text-left px-2 py-1">Model</th>
                        <th className="text-right px-2 py-1">Count</th>
                        <th className="text-right px-2 py-1">Wall p50</th>
                        <th className="text-right px-2 py-1">Wall p95</th>
                        <th className="text-right px-2 py-1">RSS p50</th>
                        <th className="text-right px-2 py-1">RSS p95</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {resourceUsage.map(r => (
                        <tr key={r.model} className="hover:bg-slate-50">
                          <td className="px-2 py-1 font-mono text-slate-700">{r.model}</td>
                          <td className="px-2 py-1 text-right text-slate-600">{r.count}</td>
                          <td className="px-2 py-1 text-right text-slate-600">{r.wallP50}s</td>
                          <td className="px-2 py-1 text-right text-slate-600">{r.wallP95}s</td>
                          <td className="px-2 py-1 text-right text-slate-600">{fmtK(r.rssP50)} KB</td>
                          <td className="px-2 py-1 text-right text-slate-600">{fmtK(r.rssP95)} KB</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </CollapsibleSection>
      )}

      {modelPerformance.length > 0 && (
        <CollapsibleSection title="Model Cost Split">
          <ModelCostDonut data={modelPerformance} />
        </CollapsibleSection>
      )}

      {tokenForecast && (
        <CollapsibleSection
          title="Token Forecast"
          badge={`~${tokenForecast.hoursLeft}h left`}
          badgeColor={tokenForecast.hoursLeft < 2 ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-500'}
          defaultOpen={tokenForecast.hoursLeft < 2}
        >
          <div className="flex items-center gap-6 text-xs">
            <div>
              <span className={`text-lg font-bold ${tokenForecast.hoursLeft < 2 ? 'text-amber-700' : 'text-slate-700'}`}>~{tokenForecast.hoursLeft}h</span>
              <span className="text-slate-400 ml-1">until exhaustion</span>
            </div>
            <div><span className="font-medium text-slate-700">{fmtK(tokenForecast.burnRatePerHour)}</span> <span className="text-slate-400">tok/hr</span></div>
            <div><span className="font-medium text-slate-700">{fmtK(tokenForecast.dailyLimit)}</span> <span className="text-slate-400">daily limit</span></div>
          </div>
          {tokenForecast.hoursLeft < 2 && (
            <div className="mt-1.5 text-xs text-amber-700 font-medium">Warning: Token budget may be exhausted within 2 hours</div>
          )}
        </CollapsibleSection>
      )}

      {qualityScores.length > 0 && (
        <CollapsibleSection title="Quality Scores" badge={qualityScores.length}>
          <div className="rounded-lg border border-slate-200 overflow-hidden">
            <table className="w-full text-[11px]">
              <thead className="bg-slate-50 text-slate-500">
                <tr>
                  <th className="text-left px-2 py-1">Phase</th>
                  <th className="text-right px-2 py-1">Avg</th>
                  <th className="text-right px-2 py-1">Latest</th>
                  <th className="text-right px-2 py-1">N</th>
                  <th className="text-left px-2 py-1">Rationale</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {qualityScores.map(q => (
                  <tr key={q.phase} className="hover:bg-slate-50">
                    <td className="px-2 py-1 font-mono text-slate-700">{q.phase}</td>
                    <td className="px-2 py-1 text-right text-slate-600">{q.avgScore.toFixed(1)}</td>
                    <td className="px-2 py-1 text-right text-slate-600">{q.latest.toFixed(1)}</td>
                    <td className="px-2 py-1 text-right text-slate-600">{q.n}</td>
                    <td className="px-2 py-1 text-slate-500 truncate max-w-[200px]" title={q.rationale}>{q.rationale}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CollapsibleSection>
      )}

      {epics.length > 0 && (
        <CollapsibleSection title="Epics" badge={epics.length}>
          <div className="space-y-1.5">
            {epics.map(e => (
              <div key={e.epicId} className="flex items-center gap-3">
                <span className="text-[11px] text-slate-700 font-medium w-40 truncate shrink-0">{e.title}</span>
                <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
                  <div className="h-full bg-emerald-500 rounded-full" style={{ width: `${e.pct}%` }} />
                </div>
                <span className="text-[10px] text-slate-500 w-16 text-right shrink-0">{e.done}/{e.total} ({e.pct}%)</span>
              </div>
            ))}
          </div>
        </CollapsibleSection>
      )}

      {decomposition.parents.length > 0 && (
        <CollapsibleSection title="Decomposition" badge={`${decomposition.effectiveness}%`} badgeColor="bg-blue-100 text-blue-700">
          <div className="space-y-1.5">
            {decomposition.parents.map(p => (
              <div key={p.id} className="flex items-center gap-2 flex-wrap">
                <span className="text-[11px] font-mono text-slate-600 shrink-0">{p.id}</span>
                {p.children.map(c => (
                  <span key={c.id} className={`text-[10px] px-1.5 py-0.5 rounded-full ${c.passes ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
                    {c.id} {c.passes ? 'pass' : 'pending'}
                  </span>
                ))}
              </div>
            ))}
          </div>
        </CollapsibleSection>
      )}

      {agentTelemetry.length > 0 && (
        <CollapsibleSection title="Agent Telemetry" badge={agentTelemetry.length}>
          <AgentTelemetryTable data={agentTelemetry} />
        </CollapsibleSection>
      )}

      {storiesList.length > 0 && (
        <CollapsibleSection title="All Stories" badge={storiesList.length}>
          <StoriesListAccordion data={storiesList} defaultFilter="failing" />
        </CollapsibleSection>
      )}

      {recentActivity.length > 0 && (
        <CollapsibleSection title="Recent Activity" badge={recentActivity.length}>
          <RecentActivityFeed data={recentActivity} />
        </CollapsibleSection>
      )}

      {latestScreenshot && (
        <CollapsibleSection title="Latest Screenshot">
          <div className="text-center">
            <img src={latestScreenshot} alt="App screenshot" className="max-w-full rounded-lg border border-slate-200 inline-block" />
          </div>
        </CollapsibleSection>
      )}

      {selectedStoryId && storyDetails?.[selectedStoryId] && (
        <StoryDetailPanel
          story={storyDetails[selectedStoryId]}
          allStories={Object.values(storyDetails)}
          attempts={storyAttempts?.[selectedStoryId]}
          onClose={() => setSelectedStoryId(null)}
        />
      )}
    </div>
  );
}
