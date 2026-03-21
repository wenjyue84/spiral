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

interface Props {
  failureReasons: FailureReason[];
  bottlenecks: Bottlenecks;
  modelPerformance: ModelPerf[];
  retryAnalysis: RetryRow[];
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

// ── Component ─────────────────────────────────────────────────────────────────

export default function FailureRetryDashboard({ failureReasons, bottlenecks, modelPerformance, retryAnalysis, onStoryClick }: Props) {
  const [showQueued, setShowQueued] = useState(false);
  const [showAll, setShowAll] = useState(false);

  const actionable = failureReasons.filter(f => f.category !== 'never_attempted');
  const queued = failureReasons.filter(f => f.category === 'never_attempted');
  const visibleFailures = showQueued ? failureReasons : actionable;
  const displayFailures = showAll ? visibleFailures : visibleFailures.slice(0, 5);
  const hasBottlenecks = bottlenecks.mostRetried.length > 0 || bottlenecks.longest.length > 0;

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

      {/* ── C. Model Performance + Retry Analysis (2-col, tight) ─────────── */}
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
            <div className="text-xs font-medium text-slate-500 mb-1 uppercase tracking-wide">Retry Analysis</div>
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
    </div>
  );
}
