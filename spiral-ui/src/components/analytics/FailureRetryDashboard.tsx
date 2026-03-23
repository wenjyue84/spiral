import { useState } from 'react';
import ErrorBreakdownChart from './ErrorBreakdownChart';

// ── Types ─────────────────────────────────────────────────────────────────────

interface FailureReason {
  id: string; title: string; reason: string;
  category: 'cost_ceiling' | 'dependency_blocked' | 'too_large' | 'rejected' | 'never_attempted' | 'pending_retry';
  retryCount: number; model: string; source: string; complexity: string;
  priority: string; dependencies: string[]; depsStatus: Array<{ id: string; met: boolean }>;
  lastAttempted: string | null; attemptCount: number;
  lastModel: string | null; lastStatus: string | null; lastDurationSec: number | null;
  scopeCreep: boolean; recommendation: string;
}

interface Bottlenecks {
  mostRetried: Array<{ id: string; title: string; retries: number }>;
  longest: Array<{ id: string; title: string; durationMin: number }>;
}

interface ModelPerf {
  model: string; total: number; kept: number; successRate: number; avgDurationSec: number;
}

interface RetryRow {
  attempt: number; total: number; kept: number; successRate: number;
}

interface StoryAttempt {
  timestamp: string; model: string; status: string;
  durationSec: number; retryNum: number; commitSha: string;
  runId: string; inputTokens: number; outputTokens: number;
}

interface StoryListItem {
  id: string; title: string; passes: boolean;
  _decomposed: boolean; _skipped: boolean; _failureReason: string;
  epicId: string; priority: string; source: string;
  attempts: StoryAttempt[];
}

interface Props {
  failureReasons: FailureReason[];
  bottlenecks: Bottlenecks;
  modelPerformance: ModelPerf[];
  retryAnalysis: RetryRow[];
  storiesList?: StoryListItem[];
  onStoryClick: (id: string) => void;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const CAT_LABEL: Record<string, string> = {
  cost_ceiling: 'Cost Ceiling', too_large: 'Too Large',
  dependency_blocked: 'Dep Blocked', rejected: 'Rejected',
  pending_retry: 'Retry Pending', never_attempted: 'Queued',
};

const CAT_BADGE: Record<string, string> = {
  cost_ceiling: 'bg-red-100 text-red-700',
  too_large: 'bg-orange-100 text-orange-700',
  dependency_blocked: 'bg-amber-100 text-amber-700',
  rejected: 'bg-rose-100 text-rose-600',
  pending_retry: 'bg-violet-100 text-violet-600',
  never_attempted: 'bg-slate-100 text-slate-500',
};

function fmtAgo(ts: string | null): string {
  if (!ts) return 'never';
  const ms = Date.now() - new Date(ts).getTime();
  const h = Math.floor(ms / 3600000);
  if (h < 1) return `${Math.floor(ms / 60000)}m ago`;
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function fmtDuration(sec: number): string {
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return s > 0 ? `${m}m${s}s` : `${m}m`;
}

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M `;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K `;
  return `${n} `;
}

function fmtTimestamp(ts: string): string {
  if (!ts) return '';
  try {
    const d = new Date(ts);
    return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
  } catch {
    return ts;
  }
}

function modelBadgeClass(model: string): string {
  if (model.includes('haiku')) return 'bg-blue-100 text-blue-700';
  if (model.includes('sonnet')) return 'bg-violet-100 text-violet-700';
  if (model.includes('opus')) return 'bg-amber-100 text-amber-700';
  return 'bg-slate-100 text-slate-600';
}

function modelShort(model: string): string {
  if (model.includes('haiku')) return 'haiku';
  if (model.includes('sonnet')) return 'sonnet';
  if (model.includes('opus')) return 'opus';
  return model || '?';
}

function modelPathBadge(model: string): string {
  if (model.includes('haiku')) return 'bg-blue-50 text-blue-600';
  if (model.includes('sonnet')) return 'bg-violet-50 text-violet-600';
  if (model.includes('opus')) return 'bg-amber-50 text-amber-700';
  return 'bg-slate-50 text-slate-500';
}

function modelPathLetter(model: string): string {
  if (model.includes('haiku')) return 'H';
  if (model.includes('sonnet')) return 'S';
  if (model.includes('opus')) return 'O';
  return model.slice(0, 3);
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function FailureRetryDashboard({ failureReasons, bottlenecks, modelPerformance, retryAnalysis, storiesList, onStoryClick }: Props) {
  const [showQueued, setShowQueued] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [expandedRetryStory, setExpandedRetryStory] = useState<string | null>(null);
  const [retryHistoryLimit, setRetryHistoryLimit] = useState(10);

  const actionable = failureReasons.filter(f => f.category !== 'never_attempted');
  const queued = failureReasons.filter(f => f.category === 'never_attempted');
  const visibleFailures = showQueued ? failureReasons : actionable;
  const displayFailures = showAll ? visibleFailures : visibleFailures.slice(0, 5);
  const hasBottlenecks = bottlenecks.mostRetried.length > 0 || bottlenecks.longest.length > 0;

  // Build retry count lookup from bottlenecks + failureReasons (retry-counts.json data)
  const retryCountLookup = new Map<string, number>();
  for (const b of bottlenecks.mostRetried) retryCountLookup.set(b.id, b.retries);
  for (const f of failureReasons) if (f.retryCount > 0) retryCountLookup.set(f.id, f.retryCount);

  // Retry history — all stories with attempts or retry counts, sorted by most recent first
  const [retrySort, setRetrySort] = useState<'recent' | 'count'>('recent');
  const retriedStories = (storiesList ?? [])
    .filter(s => s.attempts.length >= 1 || (retryCountLookup.get(s.id) ?? 0) >= 1)
    .sort((a, b) => {
      if (retrySort === 'recent') {
        const aTs = a.attempts.length > 0 ? a.attempts[a.attempts.length - 1].timestamp : '';
        const bTs = b.attempts.length > 0 ? b.attempts[b.attempts.length - 1].timestamp : '';
        return bTs.localeCompare(aTs); // newest first
      }
      // sort by count
      const aMax = Math.max(a.attempts.length, retryCountLookup.get(a.id) ?? 0);
      const bMax = Math.max(b.attempts.length, retryCountLookup.get(b.id) ?? 0);
      return bMax - aMax;
    });

  return (
    <div className="space-y-3">
      {/* ── A. Blocked Stories (dense table) ──────────────────────────────── */}
      {failureReasons.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <div className="text-xs font-medium text-slate-500 uppercase tracking-wide">
              Blocked Stories
              {actionable.length > 0 && <span className="ml-1.5 text-red-500 normal-case font-normal">{actionable.length} need attention</span>}
            </div>
            <div className="flex items-center gap-2">
              {queued.length > 0 && (
                <button
                  onClick={() => setShowQueued(q => !q)}
                  className={`text-[10px] px-2 py-0.5 rounded ${showQueued ? 'bg-slate-200 text-slate-700' : 'bg-slate-100 text-slate-400 hover:bg-slate-200'}`}
                >
                  {showQueued ? 'Hide' : 'Show'} queued ({queued.length})
                </button>
              )}
            </div>
          </div>
          <div className="rounded-lg border border-slate-200 overflow-hidden">
            <table className="w-full text-[11px]">
              <thead className="bg-slate-50 text-slate-500">
                <tr>
                  <th className="text-left px-2 py-1">Story</th>
                  <th className="text-left px-2 py-1">Category</th>
                  <th className="text-left px-2 py-1 hidden lg:table-cell">Title</th>
                  <th className="text-center px-2 py-1">Retries</th>
                  <th className="text-left px-2 py-1">Model</th>
                  <th className="text-left px-2 py-1">Deps</th>
                  <th className="text-right px-2 py-1">Last</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {displayFailures.map(f => {
                  const unmetDeps = f.depsStatus.filter(d => !d.met);
                  return (
                    <tr key={f.id} className="hover:bg-slate-50 cursor-pointer" onClick={() => onStoryClick(f.id)} title={f.recommendation}>
                      <td className="px-2 py-1">
                        <div className="flex items-center gap-1">
                          <span className="font-mono font-bold text-slate-700">{f.id}</span>
                          <span className={`text-[9px] px-1 py-0.5 rounded ${f.priority === 'high' ? 'bg-red-100 text-red-600' : f.priority === 'medium' ? 'bg-amber-100 text-amber-600' : 'bg-slate-50 text-slate-400'}`}>
                            {f.priority || '?'}
                          </span>
                          {f.scopeCreep && <span className="text-[9px] px-1 py-0.5 rounded bg-red-100 text-red-600">scope</span>}
                        </div>
                      </td>
                      <td className="px-2 py-1">
                        <span className={`text-[10px] px-1.5 py-0.5 rounded ${CAT_BADGE[f.category] ?? 'bg-slate-100 text-slate-500'}`}>
                          {CAT_LABEL[f.category] ?? f.category}
                        </span>
                      </td>
                      <td className="px-2 py-1 text-slate-600 max-w-[200px] truncate hidden lg:table-cell" title={f.title}>{f.title}</td>
                      <td className="px-2 py-1 text-center">
                        <span className={f.retryCount >= 3 ? 'text-red-600 font-bold' : 'text-slate-600'}>{f.retryCount}</span>
                      </td>
                      <td className="px-2 py-1 font-mono text-slate-500">{f.model || '?'}</td>
                      <td className="px-2 py-1">
                        {unmetDeps.length > 0
                          ? <span className="text-[10px] text-red-600 font-medium" title={unmetDeps.map(d => d.id).join(', ')}>{unmetDeps.length} unmet</span>
                          : f.depsStatus.length > 0
                            ? <span className="text-[10px] text-emerald-600">all met</span>
                            : <span className="text-[10px] text-slate-400">-</span>
                        }
                      </td>
                      <td className="px-2 py-1 text-right text-slate-400">{fmtAgo(f.lastAttempted)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {visibleFailures.length > 5 && (
            <button
              onClick={() => setShowAll(a => !a)}
              className="mt-1 text-[10px] text-violet-600 hover:text-violet-800"
            >
              {showAll ? 'Show less' : `Show all ${visibleFailures.length} stories`}
            </button>
          )}
        </div>
      )}

      {/* ── B. Error Breakdown + Bottlenecks (2-col) ─────────────────────── */}
      <div className={`grid grid-cols-1 ${hasBottlenecks ? 'lg:grid-cols-2' : ''} gap-3`}>
        <ErrorBreakdownChart />
        {hasBottlenecks && (
          <div className="space-y-2">
            {bottlenecks.mostRetried.length > 0 && (
              <div>
                <div className="text-xs font-medium text-slate-500 mb-1 uppercase tracking-wide">Most Retried</div>
                <div className="space-y-0.5">
                  {bottlenecks.mostRetried.map(b => (
                    <div
                      key={b.id}
                      className="flex items-center justify-between rounded border border-red-100 bg-red-50 px-2 py-1 cursor-pointer hover:bg-red-100 transition-colors text-[11px]"
                      onClick={() => onStoryClick(b.id)}
                    >
                      <span><span className="font-mono font-bold text-red-700">{b.id}</span> <span className="text-slate-500 truncate">{b.title}</span></span>
                      <span className="font-bold text-red-600 shrink-0 ml-2">{b.retries}x</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {bottlenecks.longest.length > 0 && (
              <div>
                <div className="text-xs font-medium text-slate-500 mb-1 uppercase tracking-wide">Slowest</div>
                <div className="space-y-0.5">
                  {bottlenecks.longest.map(b => (
                    <div
                      key={b.id}
                      className="flex items-center justify-between rounded border border-orange-100 bg-orange-50 px-2 py-1 cursor-pointer hover:bg-orange-100 transition-colors text-[11px]"
                      onClick={() => onStoryClick(b.id)}
                    >
                      <span><span className="font-mono font-bold text-orange-700">{b.id}</span> <span className="text-slate-500 truncate">{b.title}</span></span>
                      <span className="font-bold text-orange-600 shrink-0 ml-2">{b.durationMin}m</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── C. Model Performance + Success by Attempt (2-col) ──────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {modelPerformance.length > 0 && (
          <div>
            <div className="text-xs font-medium text-slate-500 mb-1 uppercase tracking-wide">Model Performance</div>
            <div className="rounded-lg border border-slate-200 overflow-hidden">
              <table className="w-full text-[11px]">
                <thead className="bg-slate-50 text-slate-500">
                  <tr>
                    <th className="text-left px-2 py-1">Model</th>
                    <th className="text-right px-2 py-1">Tries</th>
                    <th className="text-right px-2 py-1">Kept</th>
                    <th className="text-right px-2 py-1">Rate</th>
                    <th className="text-right px-2 py-1">Avg</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {modelPerformance.map(m => (
                    <tr key={m.model} className="hover:bg-slate-50">
                      <td className="px-2 py-1 font-mono text-slate-700">{m.model}</td>
                      <td className="px-2 py-1 text-right text-slate-600">{m.total}</td>
                      <td className="px-2 py-1 text-right text-slate-600">{m.kept}</td>
                      <td className="px-2 py-1 text-right">
                        <span className={m.successRate >= 70 ? 'text-emerald-600' : m.successRate >= 40 ? 'text-amber-600' : 'text-red-600'}>
                          {m.successRate}%
                        </span>
                      </td>
                      <td className="px-2 py-1 text-right text-slate-600">{m.avgDurationSec}s</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
        {retryAnalysis.length > 0 && (
          <div>
            <div className="text-xs font-medium text-slate-500 mb-1 uppercase tracking-wide">Success by Attempt #</div>
            <div className="space-y-1.5">
              {retryAnalysis.map(r => (
                <div key={r.attempt} className="flex items-center gap-2">
                  <span className="text-[11px] text-slate-500 w-14 shrink-0">Try {r.attempt}</span>
                  <div className="flex-1 h-3 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${r.successRate >= 70 ? 'bg-emerald-500' : r.successRate >= 40 ? 'bg-amber-500' : 'bg-red-500'}`}
                      style={{ width: `${Math.max(2, r.successRate)}%` }}
                    />
                  </div>
                  <span className="text-[11px] text-slate-600 w-20 text-right">{r.successRate}% ({r.kept}/{r.total})</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── D. Detailed Retry History (expandable per-story timeline) ──────── */}
      {retriedStories.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <div className="text-xs font-medium text-slate-500 uppercase tracking-wide">
              Retry History
              <span className="ml-1.5 text-violet-500 normal-case font-normal">{retriedStories.length} stories retried</span>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setRetrySort('recent')}
                className={`text-[10px] px-2 py-0.5 rounded ${retrySort === 'recent' ? 'bg-violet-100 text-violet-700 font-medium' : 'bg-slate-100 text-slate-400 hover:bg-slate-200'}`}
              >Most Recent</button>
              <button
                onClick={() => setRetrySort('count')}
                className={`text-[10px] px-2 py-0.5 rounded ${retrySort === 'count' ? 'bg-violet-100 text-violet-700 font-medium' : 'bg-slate-100 text-slate-400 hover:bg-slate-200'}`}
              >Most Retried</button>
            </div>
          </div>
          <div className="rounded-lg border border-slate-200 overflow-hidden">
            <table className="w-full text-[11px]">
              <thead className="bg-slate-50 text-slate-500">
                <tr>
                  <th className="text-left px-2 py-1 w-6"></th>
                  <th className="text-left px-2 py-1">Story</th>
                  <th className="text-left px-2 py-1 hidden lg:table-cell">Title</th>
                  <th className="text-center px-2 py-1">Attempts</th>
                  <th className="text-left px-2 py-1">Model Path</th>
                  <th className="text-left px-2 py-1">Outcome</th>
                  <th className="text-right px-2 py-1">Total Time</th>
                </tr>
              </thead>
              {retriedStories.slice(0, retryHistoryLimit).map(story => {
                const isExpanded = expandedRetryStory === story.id;
                const attempts = [...story.attempts].sort((a, b) => a.retryNum - b.retryNum);
                const models = [...new Set(attempts.map(a => a.model))];
                const totalDuration = attempts.reduce((s, a) => s + a.durationSec, 0);
                const lastAttempt = attempts[attempts.length - 1];
                const finalOutcome = story.passes ? 'passed' : story._decomposed ? 'decomposed' : story._skipped ? 'skipped' : lastAttempt?.status ?? 'pending';
                const retryJsonCount = retryCountLookup.get(story.id) ?? 0;
                const displayCount = Math.max(attempts.length, retryJsonCount);

                return (
                  <tbody key={story.id}>
                      <tr
                        className="hover:bg-slate-50 cursor-pointer border-b border-slate-100"
                        onClick={() => setExpandedRetryStory(isExpanded ? null : story.id)}
                      >
                        <td className="px-2 py-1.5 text-slate-400 text-[10px]">{isExpanded ? '\u25BC' : '\u25B6'}</td>
                        <td className="px-2 py-1.5">
                          <div className="flex items-center gap-1">
                            <span
                              className="font-mono font-bold text-slate-700 cursor-pointer hover:text-violet-600"
                              onClick={(e) => { e.stopPropagation(); onStoryClick(story.id); }}
                            >{story.id}</span>
                            <span className={`text-[9px] px-1 py-0.5 rounded ${story.priority === 'high' ? 'bg-red-100 text-red-600' : story.priority === 'medium' ? 'bg-amber-100 text-amber-600' : 'bg-slate-50 text-slate-400'}`}>
                              {story.priority || '?'}
                            </span>
                          </div>
                        </td>
                        <td className="px-2 py-1.5 text-slate-600 max-w-[180px] truncate hidden lg:table-cell" title={story.title}>{story.title}</td>
                        <td className="px-2 py-1.5 text-center">
                          <span className={displayCount >= 4 ? 'text-red-600 font-bold' : displayCount >= 3 ? 'text-amber-600 font-bold' : 'text-slate-600'}>
                            {displayCount}
                            {retryJsonCount > attempts.length && <span className="text-[9px] text-slate-400 font-normal ml-0.5">({attempts.length} logged)</span>}
                          </span>
                        </td>
                        <td className="px-2 py-1.5">
                          <div className="flex items-center gap-0.5">
                            {models.map((m, i) => (
                              <span key={i} className={`text-[9px] px-1 py-0.5 rounded font-mono ${modelPathBadge(m)}`}>
                                {modelPathLetter(m)}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="px-2 py-1.5">
                          <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                            finalOutcome === 'passed' || finalOutcome === 'keep' ? 'bg-emerald-100 text-emerald-700' :
                            finalOutcome === 'decomposed' ? 'bg-amber-100 text-amber-700' :
                            finalOutcome === 'reject' ? 'bg-red-100 text-red-600' :
                            'bg-slate-100 text-slate-500'
                          }`}>
                            {finalOutcome}
                          </span>
                        </td>
                        <td className="px-2 py-1.5 text-right text-slate-500 font-mono">{fmtDuration(totalDuration)}</td>
                      </tr>
                      {isExpanded && (
                        <tr>
                          <td colSpan={7} className="px-0 py-0">
                            <div className="bg-slate-50 border-t border-slate-200 px-4 py-2">
                              <div className="text-[10px] text-slate-400 uppercase tracking-wide mb-1.5 font-medium">Attempt Timeline</div>
                              <div className="space-y-0">
                                {attempts.map((att, idx) => (
                                  <div key={idx} className="flex items-center gap-3 py-1.5 border-b border-slate-100 last:border-0">
                                    {/* Timeline dot */}
                                    <div className="flex flex-col items-center w-4 shrink-0">
                                      <div className={`w-2.5 h-2.5 rounded-full border-2 ${
                                        att.status === 'keep' ? 'border-emerald-500 bg-emerald-100' : 'border-red-400 bg-red-100'
                                      }`} />
                                    </div>
                                    {/* Attempt # */}
                                    <span className="text-[10px] text-slate-400 w-8 shrink-0 font-mono">#{att.retryNum + 1}</span>
                                    {/* Model badge */}
                                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono w-16 text-center shrink-0 ${modelBadgeClass(att.model)}`}>
                                      {modelShort(att.model)}
                                    </span>
                                    {/* Status */}
                                    <span className={`text-[10px] font-medium w-12 shrink-0 ${att.status === 'keep' ? 'text-emerald-600' : 'text-red-500'}`}>
                                      {att.status}
                                    </span>
                                    {/* Duration */}
                                    <span className="text-[10px] text-slate-500 font-mono w-14 shrink-0">{fmtDuration(att.durationSec)}</span>
                                    {/* Tokens */}
                                    {(att.inputTokens > 0 || att.outputTokens > 0) && (
                                      <span className="text-[9px] text-slate-400 shrink-0">
                                        {fmtTokens(att.inputTokens)}in / {fmtTokens(att.outputTokens)}out
                                      </span>
                                    )}
                                    {/* Commit SHA */}
                                    {att.commitSha && (
                                      <span className="text-[9px] font-mono text-slate-400 shrink-0" title={att.commitSha}>{att.commitSha.slice(0, 7)}</span>
                                    )}
                                    {/* Timestamp */}
                                    <span className="text-[9px] text-slate-400 ml-auto shrink-0">{fmtTimestamp(att.timestamp)}</span>
                                  </div>
                                ))}
                              </div>
                              {story._failureReason && (
                                <div className="mt-2 text-[10px] text-red-600 bg-red-50 rounded px-2 py-1.5 border border-red-100">
                                  Last failure: {story._failureReason}
                                </div>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                  </tbody>
                );
              })}
            </table>
          </div>
          {retriedStories.length > retryHistoryLimit && (
            <button
              onClick={() => setRetryHistoryLimit(l => l + 10)}
              className="mt-1 text-[10px] text-violet-600 hover:text-violet-800"
            >
              Show more ({retriedStories.length - retryHistoryLimit} remaining)
            </button>
          )}
        </div>
      )}
    </div>
  );
}
