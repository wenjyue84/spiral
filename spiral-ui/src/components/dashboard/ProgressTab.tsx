import { useState } from 'react';
import StoryDetailPanel, { timeAgo, formatMYT } from '../StoryDetailPanel';
import type { StoryAttempt } from '../StoryDetailPanel';
import type { Story, TokenBurnEntry, CachePhaseEntry, ProjectData, ActiveStoryInfo } from './types';
import { pct } from './types';
import ActiveStoryBanner from './ActiveStoryBanner';
import RecentlyCompletedFeed from './RecentlyCompletedFeed';
import ThroughputMetrics from '../ThroughputMetrics';
import HealthWidget from '../HealthWidget';

export default function ProgressTab({ data, projectName, onRefresh, activeStory, isRunning }: { data: ProjectData; projectName: string; onRefresh: () => void; activeStory: ActiveStoryInfo | null; isRunning: boolean }) {
  const [deleting, setDeleting] = useState<string | null>(null);
  const [selectedStory, setSelectedStory] = useState<Story | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [priorityFilter, setPriorityFilter] = useState('all');
  const [storyPage, setStoryPage] = useState(0);
  const [showAllHistory, setShowAllHistory] = useState(false);
  const HISTORY_PREVIEW = 5;
  const PAGE_SIZE = 50;
  const p = data.progress;
  if (!p) return <div className="p-6 text-slate-500">No prd.json found in project root.</div>;

  const deleteStory = async (id: string) => {
    if (!confirm(`Delete story ${id} from prd.json? This cannot be undone.`)) return;
    setDeleting(id);
    try {
      const res = await fetch(`/api/story?name=${encodeURIComponent(projectName)}&id=${encodeURIComponent(id)}`, { method: 'DELETE' });
      if (!res.ok) { const d = await res.json() as { error?: string }; alert(d.error ?? 'Delete failed'); }
      else onRefresh();
    } catch (e) { alert(String(e)); }
    finally { setDeleting(null); }
  };

  const PRIORITY_RANK: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
  const donePct = pct(p.done, p.total);

  const storyStatusOf = (s: Story): 'pass' | 'pending' | 'failed' | 'skipped' => {
    if (s.passes) return 'pass';
    if (s.status === 'skipped' || (s.retryCount ?? 0) >= 3) return 'skipped';
    if (s.failureReason) return 'failed';
    return 'pending';
  };

  const filteredStories = p.stories
    .filter(s => {
      const q = searchQuery.trim().toLowerCase();
      if (q && !s.id.toLowerCase().includes(q) && !s.title.toLowerCase().includes(q)) return false;
      if (priorityFilter !== 'all' && s.priority !== priorityFilter) return false;
      return true;
    })
    .sort((a, b) => {
      if (a.passes !== b.passes) return a.passes ? 1 : -1;
      return (PRIORITY_RANK[a.priority ?? 'low'] ?? 99) - (PRIORITY_RANK[b.priority ?? 'low'] ?? 99);
    });
  const totalPages = Math.ceil(filteredStories.length / PAGE_SIZE);
  const pagedStories = filteredStories.slice(storyPage * PAGE_SIZE, (storyPage + 1) * PAGE_SIZE);

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
            <span className="text-xs font-medium text-emerald-600" title={formatMYT(data.lastCompletedStory.timestamp)}>
              {timeAgo(data.lastCompletedStory.timestamp)}
            </span>
          </div>
        </div>
      )}

      {/* Active story banner */}
      <ActiveStoryBanner activeStory={activeStory} />

      {/* Stats cards */}
      <div className="grid grid-cols-3 gap-4">
        <div data-testid="story-throughput" className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
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

      {/* ThroughputMetrics widget (US-1298) */}
      <ThroughputMetrics isRunning={isRunning} />

      {/* HealthWidget for SPIRAL health metrics (US-1366) */}
      <HealthWidget />

      {/* Recently Completed feed (US-314) */}
      <div>
        <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Recently Completed</div>
        <RecentlyCompletedFeed entries={data.recentlyCompleted} onStoryClick={(id) => {
          const story = p.stories.find(s => s.id === id);
          if (story) setSelectedStory(story);
        }} />
      </div>

      {/* Progress history sparkline */}
      {data.progressHistory.length > 1 && (() => {
        // Precompute story ID lists for Done and Pending tooltips
        const doneStories = p.stories
          .filter(s => s.passes)
          .map(s => s.id)
          .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
        const pendingStories = p.stories
          .filter(s => !s.passes && s.status !== 'skipped' && (s.retryCount ?? 0) < 3)
          .map(s => s.id)
          .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));

        const formatIdList = (ids: string[], max = 15): string => {
          if (ids.length === 0) return '(none)';
          const shown = ids.slice(0, max);
          const rest = ids.length - shown.length;
          return shown.join(', ') + (rest > 0 ? ` … (+${rest} more)` : '');
        };

        const doneTooltip = `Stories with passes: true\n${formatIdList(doneStories)}`;
        const pendingTooltip = `Stories not yet implemented (passes: false, not skipped)\n${formatIdList(pendingStories)}`;
        const addedTooltip = '+N means N new stories were merged into the backlog this iteration (from research or AI suggestions)';

        return (
          <div>
            <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Progress History</div>
            <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
              <table className="w-full text-xs">
                <thead className="bg-slate-50 text-slate-500">
                  <tr>
                    <th className="px-3 py-2 text-left">Time</th>
                    <th className="px-3 py-2 text-left">Iter</th>
                    <th className="px-3 py-2 text-right cursor-help" title={doneTooltip}>Done ⓘ</th>
                    <th className="px-3 py-2 text-right cursor-help" title={pendingTooltip}>Pending ⓘ</th>
                    <th className="px-3 py-2 text-right cursor-help" title={addedTooltip}>Added ⓘ</th>
                  </tr>
                </thead>
                <tbody>
                  {(() => {
                    const reversed = [...data.progressHistory].reverse();
                    const visible = showAllHistory ? reversed : reversed.slice(0, HISTORY_PREVIEW);
                    const hiddenCount = reversed.length - HISTORY_PREVIEW;
                    return (
                      <>
                        {visible.map((snap, i) => {
                          const doneCellTooltip = `${snap.done} stories passed at iter #${snap.iter}\n${formatIdList(doneStories)}`;
                          const pendingCellTooltip = `${snap.pending} stories still pending at iter #${snap.iter}\n${formatIdList(pendingStories)}`;
                          return (
                            <tr key={i} className="border-t border-slate-100">
                              <td className="px-3 py-1.5 text-slate-400" title={formatMYT(snap.ts)}>{timeAgo(snap.ts)}</td>
                              <td className="px-3 py-1.5 text-slate-600">#{snap.iter}</td>
                              <td className="px-3 py-1.5 text-right font-mono text-emerald-700 cursor-help" title={doneCellTooltip}>{snap.done}</td>
                              <td className="px-3 py-1.5 text-right font-mono text-amber-700 cursor-help" title={pendingCellTooltip}>{snap.pending}</td>
                              <td className="px-3 py-1.5 text-right font-mono text-blue-700" title={addedTooltip}>+{snap.added}</td>
                            </tr>
                          );
                        })}
                        {reversed.length > HISTORY_PREVIEW && (
                          <tr className="border-t border-slate-100">
                            <td colSpan={5} className="px-3 py-0">
                              <button
                                onClick={() => setShowAllHistory(v => !v)}
                                className="w-full py-2 text-xs text-slate-500 hover:text-blue-600 transition-colors text-left"
                              >
                                {showAllHistory ? '▲ Show less' : `▼ ${hiddenCount} older entries…`}
                              </button>
                            </td>
                          </tr>
                        )}
                      </>
                    );
                  })()}
                </tbody>
              </table>
            </div>
          </div>
        );
      })()}

      {/* Prompt cache hit rate by phase (US-223) */}
      {data.cacheStats && data.cacheStats.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Prompt Cache Hit Rate by Phase</div>
          <CacheStatsTable entries={data.cacheStats} />
        </div>
      )}

      {/* Unified Story Table */}
      <div>
        {/* Search + Filter bar */}
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <input
            type="text"
            placeholder="Search by ID or title…"
            value={searchQuery}
            onChange={e => { setSearchQuery(e.target.value); setStoryPage(0); }}
            className="flex-1 min-w-[180px] rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-400"
          />
          <div className="flex gap-1">
            {(['all', 'critical', 'high', 'medium', 'low'] as const).map(prio => (
              <button
                key={prio}
                onClick={() => { setPriorityFilter(prio); setStoryPage(0); }}
                className={`px-2.5 py-1 text-[11px] font-medium rounded-full border transition-colors ${
                  priorityFilter === prio
                    ? prio === 'all'      ? 'bg-slate-700 text-white border-slate-700'
                    : prio === 'critical' ? 'bg-red-600 text-white border-red-600'
                    : prio === 'high'     ? 'bg-orange-500 text-white border-orange-500'
                    : prio === 'medium'   ? 'bg-yellow-500 text-white border-yellow-500'
                    :                      'bg-slate-400 text-white border-slate-400'
                    : 'bg-white text-slate-500 border-slate-300 hover:border-slate-400'
                }`}
              >
                {prio === 'all' ? 'All' : prio.charAt(0).toUpperCase() + prio.slice(1)}
              </button>
            ))}
          </div>
        </div>

        {/* Count summary */}
        <div className="text-xs text-slate-500 mb-2">
          <span className="font-semibold text-slate-700">{p.done} / {p.total} stories complete ({donePct}%)</span>
          {filteredStories.length < p.total && (
            <span className="ml-2 text-slate-400">— showing {filteredStories.length} matching</span>
          )}
        </div>

        {/* Table */}
        <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 text-slate-500">
              <tr>
                <th className="px-3 py-2.5 text-left font-medium w-24">ID</th>
                <th className="px-3 py-2.5 text-left font-medium">Title</th>
                <th className="px-3 py-2.5 text-left font-medium w-20">Priority</th>
                <th className="px-3 py-2.5 text-left font-medium w-28">Status</th>
                <th className="px-3 py-2.5 text-left font-medium w-36">Completed</th>
                <th className="px-3 py-2.5 w-8"></th>
              </tr>
            </thead>
            <tbody>
              {pagedStories.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-3 py-6 text-center text-slate-400 italic">No stories match your filter.</td>
                </tr>
              ) : pagedStories.map(s => {
                const status = storyStatusOf(s);
                const statusBadge = {
                  pass:    { cls: 'bg-emerald-100 text-emerald-700 border-emerald-200', label: '✓ PASS' },
                  pending: { cls: 'bg-amber-100 text-amber-700 border-amber-200',       label: '○ PENDING' },
                  failed:  { cls: 'bg-red-100 text-red-700 border-red-200',             label: '✗ FAILED' },
                  skipped: { cls: 'bg-slate-100 text-slate-500 border-slate-200',       label: '— SKIPPED' },
                }[status];
                const priorityBadgeCls = s.priority ? (
                  s.priority === 'critical' ? 'bg-red-100 text-red-700' :
                  s.priority === 'high'     ? 'bg-orange-100 text-orange-700' :
                  s.priority === 'medium'   ? 'bg-yellow-100 text-yellow-700' :
                                              'bg-slate-100 text-slate-500'
                ) : null;
                return (
                  <tr
                    key={s.id}
                    className="border-t border-slate-100 hover:bg-slate-50 cursor-pointer group"
                    onClick={() => setSelectedStory(s)}
                  >
                    <td className="px-3 py-2 font-mono font-semibold text-blue-700 whitespace-nowrap">{s.id}</td>
                    <td className="px-3 py-2 text-slate-700 leading-snug">{s.title}</td>
                    <td className="px-3 py-2">
                      {priorityBadgeCls && (
                        <span className={`inline-block text-[10px] px-1.5 py-0.5 rounded-full font-medium ${priorityBadgeCls}`}>
                          {s.priority}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <span className={`inline-block text-[10px] px-2 py-0.5 rounded-full border font-medium whitespace-nowrap ${statusBadge.cls}`}>
                        {statusBadge.label}
                      </span>
                      {s.scopeCreep && (
                        <span className="inline-block text-[9px] px-1.5 py-0.5 rounded-full bg-purple-100 text-purple-700 border border-purple-200 font-medium ml-1" title="Scope creep detected">SCOPE</span>
                      )}
                      {!s.passes && s.lastAttempted && (() => {
                        const age = Date.now() - new Date(s.lastAttempted).getTime();
                        return age > 7 * 86400000 ? (
                          <span className="inline-block text-[9px] px-1.5 py-0.5 rounded-full bg-orange-100 text-orange-700 border border-orange-200 font-medium ml-1" title={`Last attempted ${Math.floor(age / 86400000)}d ago`}>STALE</span>
                        ) : null;
                      })()}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      {s.passes
                        ? s.completedAt
                          ? <span className="text-[10px] text-emerald-600" title={formatMYT(s.completedAt)}>{timeAgo(s.completedAt)}</span>
                          : <span className="text-[10px] text-slate-400">—</span>
                        : null}
                    </td>
                    <td className="px-3 py-2">
                      <button
                        onClick={e => { e.stopPropagation(); deleteStory(s.id); }}
                        disabled={deleting === s.id}
                        title={`Delete ${s.id}`}
                        className="opacity-0 group-hover:opacity-100 text-slate-400 hover:text-red-500 transition-opacity text-xs px-1 py-0.5 rounded hover:bg-red-50 disabled:opacity-50"
                      >
                        {deleting === s.id ? '…' : '✕'}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between mt-3">
            <span className="text-xs text-slate-400">
              Page {storyPage + 1} of {totalPages} · {filteredStories.length} stories
            </span>
            <div className="flex gap-1">
              <button
                onClick={() => setStoryPage(prev => Math.max(0, prev - 1))}
                disabled={storyPage === 0}
                className="px-2.5 py-1 text-xs rounded border border-slate-300 text-slate-500 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
              >← Prev</button>
              <button
                onClick={() => setStoryPage(prev => Math.min(totalPages - 1, prev + 1))}
                disabled={storyPage >= totalPages - 1}
                className="px-2.5 py-1 text-xs rounded border border-slate-300 text-slate-500 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
              >Next →</button>
            </div>
          </div>
        )}
      </div>

      {/* Story detail slide-in panel */}
      {selectedStory && (
        <StoryDetailPanel
          story={selectedStory}
          allStories={p.stories}
          attempts={data.storyAttempts?.[selectedStory.id]}
          onClose={() => setSelectedStory(null)}
        />
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
