import { useState, useEffect } from 'react';

// ── Types ────────────────────────────────────────────────────────────────────

export interface StoryForPanel {
  id: string;
  title: string;
  description?: string;
  passes: boolean;
  priority?: string;
  complexity?: string;
  failureReason?: string;
  dependencies?: string[];
  status?: string;
  source?: string;
  retryCount?: number;
  acceptanceCriteria?: string[];
  filesTouch?: string[];
  completedAt?: string | null;
  scopeCreep?: boolean;
  lastAttempted?: string | null;
}

export interface StoryAttempt {
  timestamp: string;
  status: string;
  model: string;
  duration: number;
  commitSha: string;
  failureRootCause?: string;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

export function formatMYT(ts: string): string {
  try {
    return new Date(ts).toLocaleString('en-MY', { timeZone: 'Asia/Kuala_Lumpur', hour12: false });
  } catch { return ts; }
}

export function timeAgo(ts: string) {
  const s = Math.floor((Date.now() - new Date(ts).getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m ago`;
}

// ── Component ────────────────────────────────────────────────────────────────

export default function StoryDetailPanel({ story, allStories, attempts, onClose }: {
  story: StoryForPanel;
  allStories: StoryForPanel[];
  attempts?: StoryAttempt[];
  onClose: () => void;
}) {
  const PRIORITY_COLOR: Record<string, string> = {
    critical: 'bg-red-100 text-red-700 border-red-200',
    high: 'bg-orange-100 text-orange-700 border-orange-200',
    medium: 'bg-yellow-100 text-yellow-700 border-yellow-200',
    low: 'bg-slate-100 text-slate-500 border-slate-200',
  };
  const SOURCE_COLOR: Record<string, string> = {
    'test-fix': 'bg-rose-100 text-rose-700',
    research: 'bg-blue-100 text-blue-700',
    seed: 'bg-purple-100 text-purple-700',
    'ai-example': 'bg-slate-100 text-slate-500',
  };

  // Close on Escape key
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [onClose]);

  // Find the passing attempt (for commit SHA and completing model)
  const passedAttempt = attempts?.find(a => a.status === 'pass') ?? null;
  const passedCommit = passedAttempt?.commitSha ?? null;
  const completingModel = passedAttempt?.model ?? null;

  // Dependency status lookup
  const storyMap = new Map(allStories.map(s => [s.id, s]));

  const [copiedSha, setCopiedSha] = useState(false);
  const copySha = (sha: string) => {
    navigator.clipboard.writeText(sha).then(() => {
      setCopiedSha(true);
      setTimeout(() => setCopiedSha(false), 2000);
    }).catch(() => { /* ignore */ });
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        className="relative z-10 bg-white shadow-2xl border-l border-slate-200 w-full max-w-lg h-full flex flex-col animate-slide-in-right"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start gap-3 px-6 py-4 border-b border-slate-100 flex-shrink-0">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs font-mono font-bold text-slate-500">{story.id}</span>
              {story.passes
                ? <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 border border-emerald-200 font-medium">✓ Complete</span>
                : <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 border border-amber-200 font-medium">○ Pending</span>}
              {story.passes && completingModel && (
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 border border-slate-200 font-mono font-medium" title="Model used in passing attempt">
                  {completingModel}
                </span>
              )}
              {story.priority && (
                <span className={`text-[10px] px-2 py-0.5 rounded-full border font-medium ${PRIORITY_COLOR[story.priority] ?? 'bg-slate-100 text-slate-500 border-slate-200'}`}>
                  {story.priority}
                </span>
              )}
              {story.complexity && (
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700 border border-indigo-200 font-medium">{story.complexity}</span>
              )}
              {story.source && (
                <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${SOURCE_COLOR[story.source] ?? 'bg-slate-100 text-slate-500'}`}>{story.source}</span>
              )}
              {(story.retryCount ?? 0) > 0 && (
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-rose-50 text-rose-600 border border-rose-100 font-medium">{story.retryCount} retr{story.retryCount === 1 ? 'y' : 'ies'}</span>
              )}
            </div>
            <h2 className="mt-1.5 text-base font-semibold text-slate-800 leading-snug">{story.title}</h2>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-700 transition-colors p-1.5 rounded-lg hover:bg-slate-100 flex-shrink-0"
            title="Close (Esc)"
          >✕</button>
        </div>

        {/* Body (scrollable) */}
        <div className="overflow-y-auto flex-1 px-6 py-4 space-y-5 text-sm">
          {/* Description */}
          {story.description ? (
            <div>
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest mb-1.5">Description</div>
              <p className="text-slate-700 leading-relaxed whitespace-pre-wrap">{story.description}</p>
            </div>
          ) : (
            <div className="text-slate-400 italic text-xs">No description provided.</div>
          )}

          {/* Acceptance Criteria */}
          {story.acceptanceCriteria && story.acceptanceCriteria.length > 0 && (
            <div>
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest mb-1.5">Acceptance Criteria</div>
              <ul className="space-y-1.5">
                {story.acceptanceCriteria.map((c, i) => (
                  <li key={i} className="flex items-start gap-2 text-slate-700">
                    <span className={`mt-0.5 flex-shrink-0 ${story.passes ? 'text-emerald-500' : 'text-slate-300'}`}>
                      {story.passes ? '✓' : '○'}
                    </span>
                    <span className="leading-snug">{c}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Dependencies with pass/fail status */}
          {story.dependencies && story.dependencies.length > 0 && (
            <div>
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest mb-1.5">Dependencies</div>
              <div className="space-y-1">
                {story.dependencies.map(depId => {
                  const dep = storyMap.get(depId);
                  const passed = dep?.passes ?? false;
                  return (
                    <div key={depId} className="flex items-center gap-2">
                      <span className={`text-xs flex-shrink-0 ${passed ? 'text-emerald-500' : 'text-amber-500'}`}>
                        {passed ? '✓' : '○'}
                      </span>
                      <span className="font-mono text-[11px] text-blue-700 font-semibold">{depId}</span>
                      {dep && <span className="text-[11px] text-slate-500 truncate">{dep.title}</span>}
                      {!dep && <span className="text-[11px] text-slate-400 italic">not found</span>}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Files to touch */}
          {story.filesTouch && story.filesTouch.length > 0 && (
            <div>
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest mb-1.5">Files</div>
              <div className="flex flex-wrap gap-1.5">
                {story.filesTouch.map((f, i) => (
                  <span key={i} className="font-mono text-[11px] bg-slate-100 text-slate-600 px-2 py-0.5 rounded">{f}</span>
                ))}
              </div>
            </div>
          )}

          {/* Attempt history from results.tsv */}
          {attempts && attempts.length > 0 && (
            <div>
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest mb-1.5">Attempt History</div>

              {/* Attempt timeline swimlane */}
              {attempts.length > 0 && (() => {
                const maxDuration = Math.max(...attempts.map(a => a.duration));
                return (
                  <div className="flex gap-1 mb-2.5 h-6 bg-slate-50 rounded px-1.5 py-1 border border-slate-100">
                    {attempts.map((a, idx) => {
                      const widthPercent = (a.duration / maxDuration) * 100;
                      let bgColor = 'bg-red-400';
                      if (a.status === 'pass') {
                        bgColor = 'bg-emerald-500';
                      } else if (idx > 0) {
                        bgColor = 'bg-amber-400';
                      }
                      const durationStr = a.duration >= 60
                        ? `${Math.floor(a.duration / 60)}m ${a.duration % 60}s`
                        : `${a.duration}s`;
                      return (
                        <div
                          key={idx}
                          className={`rounded transition-all ${bgColor} opacity-75 hover:opacity-100 cursor-pointer`}
                          style={{ width: `${widthPercent}%`, minWidth: '4px' }}
                          title={`${a.model || 'unknown'} - ${a.status} - ${durationStr}`}
                        />
                      );
                    })}
                  </div>
                );
              })()}

              <div className="rounded-lg border border-slate-200 overflow-hidden">
                <table className="w-full text-xs">
                  <thead className="bg-slate-50 text-slate-500">
                    <tr>
                      <th className="px-2.5 py-1.5 text-left">Time</th>
                      <th className="px-2.5 py-1.5 text-left">Model</th>
                      <th className="px-2.5 py-1.5 text-left">Status</th>
                      <th className="px-2.5 py-1.5 text-right">Duration</th>
                    </tr>
                  </thead>
                  <tbody>
                    {attempts.map((a, i) => (
                      <tr key={i} className="border-t border-slate-100">
                        <td className="px-2.5 py-1.5 text-slate-500" title={formatMYT(a.timestamp)}>{timeAgo(a.timestamp)}</td>
                        <td className="px-2.5 py-1.5 text-slate-600 font-mono">{a.model || '—'}</td>
                        <td className="px-2.5 py-1.5">
                          <span className={`inline-block text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                            a.status === 'pass' ? 'bg-emerald-100 text-emerald-700' :
                            a.status === 'reject' ? 'bg-red-100 text-red-700' :
                            'bg-slate-100 text-slate-500'
                          }`}>{a.status}</span>
                          {a.status === 'reject' && a.failureRootCause && (
                            <div className="mt-1 text-[10px] text-red-600 leading-snug max-w-[200px] truncate" title={a.failureRootCause}>
                              {a.failureRootCause}
                            </div>
                          )}
                        </td>
                        <td className="px-2.5 py-1.5 text-right text-slate-500">
                          {a.duration >= 60 ? `${Math.floor(a.duration / 60)}m ${a.duration % 60}s` : `${a.duration}s`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Passed commit SHA */}
          {passedCommit && (
            <div>
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest mb-1.5">Passed Commit</div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-[11px] bg-emerald-50 text-emerald-700 px-2 py-1 rounded border border-emerald-200">{passedCommit.slice(0, 8)}</span>
                <button
                  onClick={() => copySha(passedCommit)}
                  className="text-[10px] px-2 py-1 rounded border border-slate-200 text-slate-500 hover:bg-slate-50 hover:text-slate-700 transition-colors"
                >
                  {copiedSha ? '✓ Copied' : 'Copy SHA'}
                </button>
              </div>
            </div>
          )}

          {/* Failure reason */}
          {story.failureReason && (
            <div>
              <div className="text-[10px] font-semibold text-rose-400 uppercase tracking-widest mb-1.5">Failure Reason</div>
              <p className="text-rose-700 bg-rose-50 rounded-lg px-3 py-2 text-xs leading-relaxed font-mono whitespace-pre-wrap border border-rose-200">{story.failureReason}</p>
            </div>
          )}

          {/* Completion time + completing model */}
          {story.completedAt && (
            <div>
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest mb-1">Completed</div>
              <div className="flex items-center gap-3">
                <span className="text-xs text-emerald-700">{formatMYT(story.completedAt)}</span>
                {completingModel && (
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-600 border border-emerald-200 font-mono font-medium">
                    {completingModel}
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
