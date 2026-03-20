import { useState, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useParams, Link, useNavigate } from 'react-router-dom';
import DependencyGraph from './DependencyGraph';
import AnalyticsTab from './AnalyticsTab';
import StoryDetailPanel, { type StoryAttempt, formatMYT, timeAgo } from './StoryDetailPanel';
import { CONFIG_FIELDS } from '../data/configSchema';
import { useSSE, type SSEEvent } from '../hooks/useSSE';

// Config description lookup for tooltips in Settings tab
const CONFIG_DESCRIPTIONS: Record<string, { label: string; description: string }> = Object.fromEntries(
  CONFIG_FIELDS.map(f => [f.key, { label: f.label, description: f.description }])
);
void CONFIG_DESCRIPTIONS; // used for future tooltip integration

// ── Types ────────────────────────────────────────────────────────────────────

interface Story {
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

interface ActiveStatus {
  phase: string;
  iteration: number;
  started_at: number;
  pct_done: number;
  story_id?: string;
  story_title?: string;
}

interface ActiveStoryInfo {
  storyId: string | null;
  title: string | null;
}

interface ProjectData {
  name: string;
  root: string;
  lastSeen: string;
  progress: ProgressData | null;
  config: Record<string, string>;
  configRaw: string;
  constitution: string;
  activity: string;
  progressHistory: ProgressSnapshot[];
  tokenBurn?: TokenBurnEntry[];
  cacheStats?: CachePhaseEntry[];
  lastCompletedStory?: LastCompletedStory | null;
  recentlyCompleted?: LastCompletedStory[];
  checkpointTs?: string | null;
  lastLogModified?: string | null;
  activeStatus?: ActiveStatus | null;
  storyAttempts?: Record<string, StoryAttempt[]>;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function pct(done: number, total: number) {
  return total > 0 ? Math.round((done / total) * 100) : 0;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function RecentlyCompletedFeed({ entries }: { entries?: LastCompletedStory[] }) {
  const [showAll, setShowAll] = useState(false);
  const PREVIEW = 5;

  const MODEL_COLOR: Record<string, string> = {
    haiku:  'bg-sky-100 text-sky-700 border-sky-200',
    sonnet: 'bg-violet-100 text-violet-700 border-violet-200',
    opus:   'bg-amber-100 text-amber-700 border-amber-200',
  };

  const modelLabel = (model: string) => {
    if (!model) return null;
    const lower = model.toLowerCase();
    if (lower.includes('haiku'))  return { label: 'haiku',  cls: MODEL_COLOR['haiku'] };
    if (lower.includes('sonnet')) return { label: 'sonnet', cls: MODEL_COLOR['sonnet'] };
    if (lower.includes('opus'))   return { label: 'opus',   cls: MODEL_COLOR['opus'] };
    return { label: model.split('-').slice(-1)[0] ?? model, cls: 'bg-slate-100 text-slate-500 border-slate-200' };
  };

  if (!entries || entries.length === 0) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white px-4 py-6 text-center text-xs text-slate-400 italic">
        No stories completed yet.
      </div>
    );
  }

  const visible = showAll ? entries : entries.slice(0, PREVIEW);
  const hidden = entries.length - PREVIEW;

  return (
    <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
      <ul className="divide-y divide-slate-100">
        {visible.map((e, i) => {
          const badge = modelLabel(e.model ?? '');
          const truncTitle = (e.title ?? '').length > 60 ? (e.title ?? '').slice(0, 60) + '…' : (e.title ?? '');
          return (
            <li key={i} className="flex items-center gap-3 px-4 py-2.5 hover:bg-slate-50">
              <span className="text-emerald-500 flex-shrink-0 text-sm">✓</span>
              <span className="font-mono text-[11px] font-semibold text-blue-700 flex-shrink-0 w-16">{e.id}</span>
              <span className="flex-1 min-w-0 text-xs text-slate-700 truncate" title={e.title}>{truncTitle}</span>
              <div className="flex items-center gap-2 flex-shrink-0">
                {badge && (
                  <span className={`text-[10px] px-1.5 py-0.5 rounded-full border font-medium ${badge.cls}`}>
                    {badge.label}
                  </span>
                )}
                {(e.duration ?? 0) > 0 && (
                  <span className="text-[10px] text-slate-400">{e.duration}s</span>
                )}
                <span className="text-[10px] text-slate-400" title={timeAgo(e.timestamp)}>
                  {formatMYT(e.timestamp)}
                </span>
              </div>
            </li>
          );
        })}
      </ul>
      {entries.length > PREVIEW && (
        <button
          onClick={() => setShowAll(v => !v)}
          className="w-full py-2 text-xs text-slate-500 hover:text-blue-600 hover:bg-slate-50 border-t border-slate-100 transition-colors"
        >
          {showAll ? '▲ Show less' : `▼ ${hidden} more…`}
        </button>
      )}
    </div>
  );
}

// US-315: Human-readable phase names for the live status banner
const PHASE_LABELS: Record<string, string> = {
  '0': 'Clarifying',
  A:   'Generating Stories',
  R:   'Researching',
  T:   'Synthesizing Tests',
  S:   'Validating Stories',
  M:   'Merging',
  I:   'Implementing',
  V:   'Validating',
  C:   'Checking Completion',
  G:   'Generating Stories',
};

function LiveStatusBanner({ activeStatus, lastCompletedStory, checkpointTs, lastLogModified, isRunning }: {
  activeStatus?: ActiveStatus | null;
  lastCompletedStory?: LastCompletedStory | null;
  checkpointTs?: string | null;
  lastLogModified?: string | null;
  isRunning?: boolean;
}) {
  const truncate = (s: string, max = 50) => s.length > max ? s.slice(0, max) + '…' : s;

  if (activeStatus) {
    const phaseName = PHASE_LABELS[activeStatus.phase] ?? `Phase ${activeStatus.phase}`;
    const storyTitle = activeStatus.story_title ? truncate(activeStatus.story_title) : null;
    return (
      <div className="flex items-center gap-3 px-5 py-2 bg-emerald-50 border-b border-emerald-200 flex-shrink-0">
        <span className="relative flex h-2.5 w-2.5 flex-shrink-0">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
          <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500" />
        </span>
        <span className="text-xs font-bold text-emerald-700 tracking-wide">SPIRAL IS RUNNING</span>
        <span className="h-3.5 w-px bg-emerald-300 flex-shrink-0" />
        <span className="text-xs text-emerald-600 font-medium">{phaseName}</span>
        {storyTitle && (
          <>
            <span className="h-3.5 w-px bg-emerald-300 flex-shrink-0" />
            <span className="text-xs text-emerald-700 font-mono truncate max-w-xs">{storyTitle}</span>
          </>
        )}
        {activeStatus.story_id && (
          <span className="text-[10px] text-emerald-500 font-mono flex-shrink-0">{activeStatus.story_id}</span>
        )}
        <span className="ml-auto text-[10px] text-emerald-500 flex-shrink-0">iter #{activeStatus.iteration}</span>
      </div>
    );
  }

  // No activeStatus but log/checkpoint was recently modified — between phases
  if (isRunning) {
    const lastRunTs = lastCompletedStory?.timestamp ?? checkpointTs ?? lastLogModified ?? null;
    return (
      <div
        className="flex items-center gap-3 px-5 py-2 bg-emerald-50 border-b border-emerald-200 flex-shrink-0"
        title="SPIRAL is active (log or checkpoint updated within 2 min) but no active phase is reported yet — likely transitioning between phases."
      >
        <span className="relative flex h-2.5 w-2.5 flex-shrink-0">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
          <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500" />
        </span>
        <span className="text-xs font-bold text-emerald-700 tracking-wide">SPIRAL IS RUNNING</span>
        <span className="h-3.5 w-px bg-emerald-300 flex-shrink-0" />
        <span className="text-xs text-emerald-600 font-medium italic">Between phases…</span>
        {lastRunTs && (
          <>
            <span className="h-3.5 w-px bg-emerald-300 flex-shrink-0" />
            <span className="text-xs text-emerald-500">Last activity: {timeAgo(lastRunTs)}</span>
          </>
        )}
      </div>
    );
  }

  // Idle: find last run time
  const lastRunTs = lastCompletedStory?.timestamp ?? checkpointTs ?? lastLogModified ?? null;
  return (
    <div
      className="flex items-center gap-3 px-5 py-2 bg-slate-50 border-b border-slate-100 flex-shrink-0"
      title="SPIRAL is idle — no log or checkpoint updates detected in the last 2 minutes."
    >
      <span className="relative flex h-2.5 w-2.5 flex-shrink-0">
        <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-slate-300" />
      </span>
      <span className="text-xs font-medium text-slate-500">Idle</span>
      {lastRunTs && (
        <>
          <span className="h-3.5 w-px bg-slate-200 flex-shrink-0" />
          <span className="text-xs text-slate-400">Last run: {timeAgo(lastRunTs)}</span>
        </>
      )}
    </div>
  );
}

function ActiveStoryBanner({ activeStory, className }: { activeStory: ActiveStoryInfo | null; className?: string }) {
  if (!activeStory?.storyId) return null;
  const truncate = (s: string, max = 60) => s.length > max ? s.slice(0, max) + '…' : s;
  return (
    <div className={`flex items-center gap-2 px-4 py-2 bg-amber-50 border border-amber-200 rounded-xl ${className ?? ''}`}>
      <span className="relative flex h-2 w-2 flex-shrink-0">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
        <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-500" />
      </span>
      <span className="text-xs font-semibold text-amber-700">Ralph is working on:</span>
      <span className="text-xs font-mono font-bold text-amber-800">{activeStory.storyId}</span>
      {activeStory.title && (
        <span className="text-xs text-amber-700">— {truncate(activeStory.title)}</span>
      )}
    </div>
  );
}

function ProgressTab({ data, projectName, onRefresh, activeStory }: { data: ProjectData; projectName: string; onRefresh: () => void; activeStory: ActiveStoryInfo | null }) {
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

      {/* Recently Completed feed (US-314) */}
      <div>
        <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Recently Completed</div>
        <RecentlyCompletedFeed entries={data.recentlyCompleted} />
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

/** Update key=value lines in raw config content, preserving comments. */
function buildUpdatedConfig(rawContent: string, updates: Record<string, string>): string {
  const handled = new Set<string>();
  const result = rawContent.split('\n').map(line => {
    const m = line.match(/^(\s*(?:export\s+)?)([A-Z_][A-Z0-9_]*)=(["']?)([^#\n]*?)\3(\s*#.*)?$/);
    if (m) {
      const key = m[2];
      if (key in updates) {
        handled.add(key);
        const val = updates[key].replace(/"/g, '\\"');
        return `${m[1]}${key}="${val}"${m[5] ? '  ' + m[5].trim() : ''}`;
      }
    }
    return line;
  });
  const newKeys = Object.entries(updates).filter(([k]) => !handled.has(k));
  if (newKeys.length > 0) {
    result.push('');
    result.push('# Added via SPIRAL UI');
    for (const [k, v] of newKeys) result.push(`export ${k}="${v.replace(/"/g, '\\"')}"`);
  }
  return result.join('\n');
}

function SettingsTab({ config, configRaw, projectName, onConfigSaved }: {
  config: Record<string, string>;
  configRaw: string;
  projectName: string;
  onConfigSaved?: () => void;
}) {
  const [edited, setEdited] = useState<Record<string, string>>(() => ({ ...config }));
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ ok: boolean; text: string } | null>(null);

  // Reset edited state when config changes (e.g. after save + refresh)
  useEffect(() => { setEdited({ ...config }); }, [JSON.stringify(config)]); // eslint-disable-line

  const knownKeys = new Set(CONFIG_FIELDS.map(f => f.key));
  const unknownKeys = Object.keys(config).filter(k => !knownKeys.has(k));

  // All rows: known CONFIG_FIELDS that exist in config, plus unknown raw keys
  const rows = [
    ...CONFIG_FIELDS.filter(f => f.key in config),
    ...unknownKeys.map(k => ({ key: k, label: k, description: '', type: 'text' as const, options: undefined })),
  ];

  const handleSave = async () => {
    setSaving(true);
    setSaveMsg(null);
    try {
      const newContent = buildUpdatedConfig(configRaw, edited);
      const res = await fetch('/api/save-config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: newContent, name: projectName }),
      });
      const d = await res.json() as { ok?: boolean; error?: string };
      if (d.ok) { setSaveMsg({ ok: true, text: 'Saved!' }); onConfigSaved?.(); }
      else setSaveMsg({ ok: false, text: d.error ?? 'Save failed' });
    } catch (e) {
      setSaveMsg({ ok: false, text: String(e) });
    } finally { setSaving(false); }
  };

  if (rows.length === 0) {
    return <div className="p-6 text-slate-500">No spiral.config.sh found for this project.</div>;
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-700">spiral.config.sh</h3>
          <p className="text-xs text-slate-400 mt-0.5">Edit values and click Save to write to disk.</p>
        </div>
        <div className="flex items-center gap-3">
          {saveMsg && (
            <span className={`text-xs font-medium ${saveMsg.ok ? 'text-emerald-600' : 'text-red-600'}`}>{saveMsg.text}</span>
          )}
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-1.5 bg-blue-600 text-white text-xs font-semibold rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save Config'}
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-slate-50 text-slate-500">
            <tr>
              <th className="px-4 py-2.5 text-left font-medium w-2/5">Variable</th>
              <th className="px-4 py-2.5 text-left font-medium">Value</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(f => {
              const val = edited[f.key] ?? '';
              return (
                <tr key={f.key} className="border-t border-slate-100 hover:bg-slate-50">
                  <td className="px-4 py-2.5 align-top">
                    <div className="font-mono text-blue-700 whitespace-nowrap">{f.key}</div>
                    {f.label !== f.key && <div className="text-[10px] text-slate-400 mt-0.5">{f.label}</div>}
                    {f.description && (
                      <div className="text-[10px] text-slate-400 mt-0.5 max-w-xs leading-tight">
                        {f.description.length > 100 ? f.description.slice(0, 100) + '…' : f.description}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-2 align-middle">
                    {f.type === 'select' && f.options ? (
                      <select
                        className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-400"
                        value={val}
                        onChange={e => setEdited(p => ({ ...p, [f.key]: e.target.value }))}
                      >
                        {f.options.map(opt => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
                      </select>
                    ) : f.type === 'toggle' ? (
                      <button
                        type="button"
                        onClick={() => setEdited(p => ({ ...p, [f.key]: val === 'true' ? 'false' : 'true' }))}
                        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${val === 'true' ? 'bg-blue-600' : 'bg-slate-300'}`}
                      >
                        <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${val === 'true' ? 'translate-x-6' : 'translate-x-1'}`} />
                      </button>
                    ) : (
                      <input
                        type={f.type === 'number' ? 'number' : 'text'}
                        className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-blue-400"
                        value={val}
                        onChange={e => setEdited(p => ({ ...p, [f.key]: e.target.value }))}
                      />
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ConstitutionTab({ text, projectName }: { text: string; projectName?: string }) {
  const [draft, setDraft] = useState(text);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => { setDraft(text); }, [text]);

  if (!text && draft === '') {
    return (
      <div className="p-6 text-slate-500">
        No constitution found. Set <code className="bg-slate-100 px-1 rounded">SPIRAL_SPECKIT_CONSTITUTION</code> in your config,
        or create <code className="bg-slate-100 px-1 rounded">.specify/memory/constitution.md</code> in your project root.
      </div>
    );
  }

  const lineCount = draft.split('\n').length;
  const isTooLong = lineCount > 150;
  const isDirty = draft !== text;

  async function handleSave() {
    setSaving(true);
    setError('');
    try {
      const res = await fetch('/api/save-constitution', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: draft, name: projectName }),
      });
      const data = await res.json() as { ok?: boolean; error?: string };
      if (!data.ok) throw new Error(data.error ?? 'Save failed');
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="p-6 flex flex-col gap-3 h-full">
      <div className="flex items-center gap-3">
        <span className="text-xs text-slate-500 font-mono">{lineCount} lines</span>
        {isTooLong && (
          <span className="flex items-center gap-1 text-xs font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-0.5">
            ⚠ Constitution is long ({lineCount} lines). Consider trimming — LLMs may not reliably follow rules past ~150 lines.
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {error && <span className="text-xs text-red-600">{error}</span>}
          {saved && <span className="text-xs text-green-600 font-medium">✓ Saved</span>}
          <button
            onClick={handleSave}
            disabled={saving || !isDirty}
            className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
              isDirty
                ? 'bg-blue-600 hover:bg-blue-700 text-white'
                : 'bg-slate-100 text-slate-400 cursor-not-allowed'
            }`}
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
      <textarea
        value={draft}
        onChange={e => setDraft(e.target.value)}
        className="flex-1 w-full rounded-xl border border-slate-200 bg-white p-5 text-xs text-slate-700 font-mono leading-relaxed resize-none focus:outline-none focus:ring-2 focus:ring-blue-300"
        spellCheck={false}
        style={{ minHeight: '400px' }}
      />
    </div>
  );
}

function SkillsTab({ projectName }: { projectName?: string }) {
  const [skills, setSkills] = useState<{ name: string }[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [content, setContent] = useState('');
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');
  const [loadingSkill, setLoadingSkill] = useState(false);

  useEffect(() => {
    const qs = projectName ? `?name=${encodeURIComponent(projectName)}` : '';
    fetch(`/api/skills${qs}`)
      .then(r => r.json() as Promise<{ skills: { name: string }[] }>)
      .then(d => {
        setSkills(d.skills ?? []);
        if (d.skills?.length && !selected) setSelected(d.skills[0].name);
      })
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectName]);

  useEffect(() => {
    if (!selected) return;
    setLoadingSkill(true);
    setError('');
    const qs = projectName ? `&name=${encodeURIComponent(projectName)}` : '';
    fetch(`/api/skill?skill=${encodeURIComponent(selected)}${qs}`)
      .then(r => r.json() as Promise<{ content?: string; error?: string }>)
      .then(d => {
        if (d.error) { setError(d.error); return; }
        setContent(d.content ?? '');
        setDraft(d.content ?? '');
      })
      .catch(e => setError(String(e)))
      .finally(() => setLoadingSkill(false));
  }, [selected, projectName]);

  async function handleSave() {
    if (!selected) return;
    setSaving(true);
    setError('');
    try {
      const res = await fetch('/api/save-skill', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: draft, skillName: selected, name: projectName }),
      });
      const data = await res.json() as { ok?: boolean; error?: string };
      if (!data.ok) throw new Error(data.error ?? 'Save failed');
      setContent(draft);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  const lineCount = draft.split('\n').length;
  const isDirty = draft !== content;

  return (
    <div className="flex h-full">
      <div className="w-48 shrink-0 border-r border-slate-200 bg-slate-50 flex flex-col">
        <div className="px-3 py-2 text-xs font-semibold text-slate-500 uppercase tracking-wide border-b border-slate-200">
          Skills
        </div>
        <div className="flex-1 overflow-y-auto py-1">
          {skills.length === 0 && (
            <div className="px-3 py-3 text-xs text-slate-400 italic">No skills found in ralph/skills/</div>
          )}
          {skills.map(s => (
            <button
              key={s.name}
              onClick={() => { setSelected(s.name); setError(''); }}
              className={`w-full text-left px-3 py-2 text-xs font-mono truncate transition-colors ${
                selected === s.name
                  ? 'bg-blue-50 text-blue-700 font-semibold border-r-2 border-blue-600'
                  : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              {s.name}
            </button>
          ))}
        </div>
      </div>
      <div className="flex-1 flex flex-col overflow-hidden">
        {!selected ? (
          <div className="p-6 text-slate-500 text-sm">Select a skill from the sidebar.</div>
        ) : loadingSkill ? (
          <div className="p-6 text-slate-400 text-sm">Loading…</div>
        ) : (
          <div className="p-6 flex flex-col gap-3 h-full">
            <div className="flex items-center gap-3">
              <span className="text-xs font-mono text-slate-500">{selected}.md</span>
              <span className="text-xs text-slate-400">·</span>
              <span className="text-xs text-slate-500 font-mono">{lineCount} lines</span>
              <div className="ml-auto flex items-center gap-2">
                {error && <span className="text-xs text-red-600">{error}</span>}
                {saved && <span className="text-xs text-green-600 font-medium">✓ Saved</span>}
                <button
                  onClick={handleSave}
                  disabled={saving || !isDirty}
                  className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
                    isDirty
                      ? 'bg-blue-600 hover:bg-blue-700 text-white'
                      : 'bg-slate-100 text-slate-400 cursor-not-allowed'
                  }`}
                >
                  {saving ? 'Saving…' : 'Save'}
                </button>
              </div>
            </div>
            <textarea
              value={draft}
              onChange={e => setDraft(e.target.value)}
              className="flex-1 w-full rounded-xl border border-slate-200 bg-white p-5 text-xs text-slate-700 font-mono leading-relaxed resize-none focus:outline-none focus:ring-2 focus:ring-blue-300"
              spellCheck={false}
              style={{ minHeight: '400px' }}
            />
          </div>
        )}
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

/** Strip ANSI escape sequences from a string. */
function stripAnsi(s: string): string {
  return s.replace(/\x1b\[[0-9;]*[mGKHFJ]/g, '').replace(/\u001b\[[0-9;]*[mGKHFJ]/g, '');
}

/**
 * Process a log line for display:
 *   1. Strip ANSI escape codes
 *   2. Convert ISO timestamps → MYT
 *   3. Convert elapsed [M:SS] / [H:MM:SS] → absolute MYT using phaseStart as T=0
 */
function processLogLine(line: string, phaseStart: Date | null = null): string {
  let out = stripAnsi(line);
  // ISO timestamps → MYT
  out = out.replace(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})/g, (match) => {
    try {
      return new Date(match).toLocaleString('en-MY', { timeZone: 'Asia/Kuala_Lumpur', hour12: false, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch { return match; }
  });
  // Elapsed [M:SS] or [H:MM:SS] → absolute MYT
  if (phaseStart) {
    out = out.replace(/\[(\d+):(\d{2})(?::(\d{2}))?\]/g, (_m, p1, p2, p3) => {
      const secs = p3 !== undefined
        ? parseInt(p1) * 3600 + parseInt(p2) * 60 + parseInt(p3)
        : parseInt(p1) * 60 + parseInt(p2);
      const abs = new Date(phaseStart.getTime() + secs * 1000);
      const myt = abs.toLocaleString('en-MY', { timeZone: 'Asia/Kuala_Lumpur', hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
      return `[${myt}]`;
    });
  }
  return out;
}

interface PhaseIMetrics {
  storyBudgets: { id: string; budget: number }[];
  spawnCount: number;
  undoCount: number;
  baselineTests: string | null;
  latestTests: string | null;
  latestFailing: string | null;
  lastAction: string | null;
  stashed: boolean;
}

/** Parse Phase I log lines into key operational metrics. */
function extractPhaseIMetrics(lines: string[]): PhaseIMetrics {
  const clean = lines.map(stripAnsi);
  const storyBudgets: { id: string; budget: number }[] = [];
  for (const l of clean) {
    const m = l.match(/\[I\]\s+Budget:\s+(\d+)s\s+for\s+((?:US|UT)-\d+)/);
    if (m) storyBudgets.push({ id: m[2], budget: parseInt(m[1]) });
  }
  const spawnCount = clean.filter(l => /\[spawn\]\s+Fresh claude instance/.test(l)).length;
  const undoCount  = clean.filter(l => /\[undo\]\s+Worktree reset/.test(l)).length;
  const baselineMatch = clean.find(l => /\[baseline\].*pre-story.*passing/.test(l));
  const baselineTests = baselineMatch?.match(/(\d+)\s+passing/)?.[1] ?? null;
  const testLines     = clean.filter(l => /\d+\s+passing/.test(l));
  const latestTests   = testLines[testLines.length - 1]?.match(/(\d+)\s+passing/)?.[1] ?? null;
  const failLines     = clean.filter(l => /\d+\s+failing/.test(l));
  const latestFailing = failLines[failLines.length - 1]?.match(/(\d+)\s+failing/)?.[1] ?? null;
  const actionLines   = clean.filter(l => /^\s*\[(spawn|baseline|undo|model|completeness|precontext|cache|speckit)\]/.test(l));
  const lastAction    = actionLines[actionLines.length - 1]?.trim() ?? null;
  const stashed       = clean.some(l => /Stash created/.test(l));
  return { storyBudgets, spawnCount, undoCount, baselineTests, latestTests, latestFailing, lastAction, stashed };
}

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

function WorkersTab({ projectName, activeStory }: { projectName: string; activeStory: ActiveStoryInfo | null }) {
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

function ActivityTab({ log, activeStory }: { log: string; activeStory: ActiveStoryInfo | null }) {
  const [maximized, setMaximized] = useState(false);
  const [copied, setCopied] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!maximized) return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setMaximized(false); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [maximized]);

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [log, autoScroll, maximized]);

  if (!log) {
    return <div className="p-6 text-slate-500">No activity log yet. Start SPIRAL to see live output here.</div>;
  }

  const lines = log.split('\n').filter(Boolean);
  const processed = lines.map(toMYT).join('\n');
  const now = new Date().toLocaleString('en-MY', { timeZone: 'Asia/Kuala_Lumpur', hour12: false });

  const handleCopy = () => {
    void navigator.clipboard.writeText(processed);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    if (!atBottom) setAutoScroll(false);
  };

  const toolbar = (
    <div className="flex items-center justify-between px-3 py-1.5 bg-slate-900 border-b border-slate-800">
      <span className="text-[10px] text-slate-500 font-mono">
        {lines.length} lines · elapsed→MYT
        {maximized && <span className="ml-2 text-blue-400">Activity Log</span>}
      </span>
      <div className="flex items-center gap-1">
        <button
          onClick={() => { setAutoScroll(true); if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight; }}
          title="Scroll to bottom"
          className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono transition-all ${
            autoScroll ? 'bg-emerald-700 text-white' : 'bg-slate-700 hover:bg-slate-600 text-slate-300'
          }`}
        >
          ↓ Bottom
        </button>
        <button
          onClick={() => setMaximized(prev => !prev)}
          title={maximized ? 'Restore (Esc)' : 'Maximize to fullscreen'}
          className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono transition-all ${
            maximized ? 'bg-blue-600 text-white' : 'bg-slate-700 hover:bg-slate-600 text-slate-300'
          }`}
        >
          {maximized ? '⊡ Restore' : '⊞ Max'}
        </button>
        <button
          onClick={handleCopy}
          title="Copy log to clipboard"
          className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono transition-all ${
            copied ? 'bg-emerald-600 text-white' : 'bg-slate-700 hover:bg-slate-600 text-slate-300'
          }`}
        >
          {copied ? '✓ Copied' : '⎘ Copy'}
        </button>
      </div>
    </div>
  );

  const logBody = (
    <div
      ref={scrollRef}
      onScroll={handleScroll}
      className={`overflow-auto ${maximized ? 'flex-1' : 'max-h-[600px]'}`}
    >
      <pre className="p-4 text-[11px] text-slate-300 font-mono leading-relaxed whitespace-pre-wrap">
        {processed}
      </pre>
    </div>
  );

  const inner = (
    <div className={`rounded-xl bg-slate-950 overflow-hidden ${maximized ? 'flex flex-col h-full' : ''}`}>
      {toolbar}
      {logBody}
    </div>
  );

  return (
    <div className="p-6 space-y-3">
      <ActiveStoryBanner activeStory={activeStory} />
      <div className="flex items-center justify-between">
        <div className="text-[10px] text-slate-400">Timestamps shown in Malaysia Time (MYT, UTC+8)</div>
        <div className="text-[10px] text-slate-400">Now: {now}</div>
      </div>
      {maximized
        ? createPortal(
            <div className="fixed inset-0 z-[9999] bg-slate-950 flex flex-col p-4">
              <ActiveStoryBanner activeStory={activeStory} className="mb-2" />
              <div className="flex-1 flex flex-col min-h-0 rounded-xl overflow-hidden">
                {toolbar}
                {logBody}
              </div>
            </div>,
            document.body
          )
        : inner
      }
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
  bypassed?: boolean;
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

const PHASE_ENABLED_DEFAULTS: Record<string, boolean> = {
  A: true, R: false, T: true, S: true, M: true, I: true, V: true, P: true, C: true,
};

// Story shape inside phase output files
interface OutputFileStory {
  id?: string;
  title?: string;
  priority?: string;
  _source?: string;
  [key: string]: unknown;
}

const OUTPUT_FILE_PATHS: Record<string, string> = {
  aiSuggestions: '.spiral/_ai_suggestions_output.json',
  research:      '.spiral/_research_output.json',
  testStories:   '.spiral/_test_stories_output.json',
  validated:     '.spiral/_validated_stories.json',
  overflow:      '.spiral/_research_overflow.json',
};

const SOURCE_COLORS: Record<string, string> = {
  'test-fix':   'bg-violet-100 text-violet-700 border-violet-200',
  'research':   'bg-blue-100 text-blue-700 border-blue-200',
  'ai-example': 'bg-indigo-100 text-indigo-700 border-indigo-200',
  'seed':       'bg-slate-100 text-slate-600 border-slate-200',
};

const PRIORITY_BADGE: Record<string, string> = {
  critical: 'bg-red-100 text-red-700 border-red-200',
  high:     'bg-orange-100 text-orange-700 border-orange-200',
  medium:   'bg-yellow-100 text-yellow-700 border-yellow-200',
  low:      'bg-slate-100 text-slate-500 border-slate-200',
};

function PhaseTraceTab({ projectName, stories, activeStory }: { projectName: string; stories?: Story[]; activeStory: ActiveStoryInfo | null }) {
  const [traceData, setTraceData] = useState<PhaseTraceData | null>(null);
  const [selectedIter, setSelectedIter] = useState<number | null>(null);
  const [expandedPhases, setExpandedPhases] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [phaseEnabled, setPhaseEnabled] = useState<Record<string, boolean>>(PHASE_ENABLED_DEFAULTS);
  const [savingPhase, setSavingPhase] = useState<string | null>(null);
  const [phaseChanged, setPhaseChanged] = useState(false);
  const [selectedOutputFile, setSelectedOutputFile] = useState<keyof PhaseOutputs | null>(null);
  const [maximizedPhase, setMaximizedPhase] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [selectedPhaseNavKey, setSelectedPhaseNavKey] = useState<string | null>(null);
  const userSelectedRef = useRef(false);

  useEffect(() => {
    if (!maximizedPhase) return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setMaximizedPhase(null); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [maximizedPhase]);

  useEffect(() => {
    const load = async () => {
      try {
        const [traceRes, cfgRes] = await Promise.all([
          fetch(`/api/phase-trace?name=${encodeURIComponent(projectName)}`),
          fetch(`/api/phase-config?name=${encodeURIComponent(projectName)}`),
        ]);
        if (traceRes.ok) {
          const data = await traceRes.json() as PhaseTraceData;
          setTraceData(data);
          // Auto-select latest iteration only on first load (before user clicks)
          if (data.iterations.length > 0 && !userSelectedRef.current) {
            setSelectedIter(data.iterations[data.iterations.length - 1].iter);
          }
        }
        if (cfgRes.ok) {
          const cfg = await cfgRes.json() as Record<string, boolean>;
          setPhaseEnabled(cfg);
        }
      } catch { /* ignore */ }
      setLoading(false);
    };
    load();
    const interval = setInterval(load, 15_000);
    return () => clearInterval(interval);
  }, [projectName]);

  const togglePhaseEnabled = async (phaseId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const next = { ...phaseEnabled, [phaseId]: !phaseEnabled[phaseId] };
    setPhaseEnabled(next);
    setSavingPhase(phaseId);
    try {
      const res = await fetch(`/api/phase-config?name=${encodeURIComponent(projectName)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config: next }),
      });
      if (res.ok) {
        setPhaseChanged(true);
        setTimeout(() => setPhaseChanged(false), 60_000);
      }
    } catch { /* ignore */ }
    setSavingPhase(null);
  };

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

  // Find phase_start and phase_end events for duration/timing display
  const phaseStartEvents = traceData.phaseEvents.filter(
    e => (e.event === 'phase_start' || e.type === 'phase_start') && e.iteration === currentIter.iter
  );
  const phaseEndEvents = traceData.phaseEvents.filter(
    e => (e.event === 'phase_end' || e.type === 'phase_end') && e.iteration === currentIter.iter
  );

  const getDuration = (phase: string): number | null => {
    const ev = phaseEndEvents.find(e => e.phase === phase);
    if (ev?.duration_s == null) return null;
    return Math.max(0, ev.duration_s);
  };

  const getStartTs = (phase: string): string | null => {
    const ev = phaseStartEvents.find(e => e.phase === phase);
    return ev?.ts ?? null;
  };

  const getEndTs = (phase: string): string | null => {
    const ev = phaseEndEvents.find(e => e.phase === phase);
    return ev?.ts ?? null;
  };

  /** Format duration as human-readable string */
  const fmtDuration = (s: number): string => {
    if (s >= 3600) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m ${s % 60}s`;
    if (s >= 60) return `${Math.floor(s / 60)}m ${s % 60}s`;
    return `${s}s`;
  };

  /** Format time as MYT HH:MM:SS */
  const fmtTime = (ts: string): string => {
    try {
      return new Date(ts).toLocaleString('en-MY', { timeZone: 'Asia/Kuala_Lumpur', hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch { return ts; }
  };

  // Compute iteration total duration from earliest start to latest end
  const iterStartTs = phaseStartEvents.length > 0
    ? phaseStartEvents.reduce((earliest, e) => (!earliest || (e.ts && e.ts < earliest) ? e.ts! : earliest), '')
    : null;
  const iterEndTs = phaseEndEvents.length > 0
    ? phaseEndEvents.reduce((latest, e) => (!latest || (e.ts && e.ts > latest) ? e.ts! : latest), '')
    : null;
  const iterTotalDuration = iterStartTs && iterEndTs
    ? Math.max(0, Math.round((new Date(iterEndTs).getTime() - new Date(iterStartTs).getTime()) / 1000))
    : null;

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
    <div className="flex min-h-full">

      {/* ── Left navigation sidebar ─────────────────────────────────────── */}
      <aside className="w-52 shrink-0 sticky top-0 h-screen overflow-y-auto border-r border-slate-200 bg-white z-10">
        <div className="pt-4 pb-6 px-2">

          {/* Iteration selector */}
          <div className="mb-4 px-1">
            <div className="text-[9px] font-semibold text-slate-400 uppercase tracking-widest mb-2 px-2">Iteration</div>
            <div className="flex flex-wrap gap-1 px-1">
              {traceData.iterations.map(iter => (
                <button
                  key={iter.iter}
                  onClick={() => { userSelectedRef.current = true; setSelectedIter(iter.iter); setExpandedPhases(new Set()); setSelectedPhaseNavKey(null); }}
                  className={`px-2 py-0.5 text-xs font-mono rounded-md border transition-colors ${
                    iter.iter === currentIter.iter
                      ? 'bg-blue-600 text-white border-blue-600'
                      : 'bg-white text-slate-600 border-slate-200 hover:border-blue-300 hover:bg-blue-50'
                  }`}
                >
                  #{iter.iter}
                </button>
              ))}
            </div>
            {iterTotalDuration !== null && (
              <div className="mt-2 px-2 text-[10px] font-mono text-slate-500">
                Total: <span className="font-semibold text-blue-700">{fmtDuration(iterTotalDuration)}</span>
              </div>
            )}
          </div>

          {/* Phase list */}
          <div className="mb-1.5 px-3 text-[9px] font-semibold text-slate-400 uppercase tracking-widest">
            Phases
            <span className="ml-1 normal-case font-normal text-slate-300">
              ({currentIter.phases.filter(p => p.phase !== 'G').length})
            </span>
          </div>
          {currentIter.phases
            .filter(p => p.phase !== 'G')
            .sort((a, b) => (PHASE_ORDER[a.phase] ?? 99) - (PHASE_ORDER[b.phase] ?? 99))
            .map(phase => {
              const colors = PHASE_COLORS[phase.phase] ?? { bg: 'bg-slate-50', border: 'border-slate-200', text: 'text-slate-700', dot: 'bg-slate-400' };
              const phaseName = PHASE_NAMES[phase.phase] ?? `Phase ${phase.phase}`;
              const duration = getDuration(phase.phase);
              const isBypassed = phase.bypassed === true;
              const isNotYetRun = !isBypassed && (phase.label.endsWith('(not run)') || phase.lineStart === -1);
              const isSkipped = isBypassed || isNotYetRun;
              const isSelected = selectedPhaseNavKey === phase.phase;
              const isActive = phase.phase === 'I' && activeStory?.storyId != null;
              return (
                <button
                  key={phase.phase}
                  onClick={() => !isSkipped && setSelectedPhaseNavKey(isSelected ? null : phase.phase)}
                  className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg text-left transition-colors mb-0.5 ${
                    isSkipped
                      ? 'opacity-40 cursor-default'
                      : isSelected
                        ? `${colors.bg} border ${colors.border}`
                        : 'hover:bg-slate-50 border border-transparent text-slate-600'
                  }`}
                >
                  <div className={`w-2 h-2 rounded-full flex-shrink-0 ${isSkipped ? 'bg-slate-300' : colors.dot}`} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className={`text-[11px] font-mono font-bold ${isSelected ? colors.text : 'text-slate-700'}`}>
                        {phase.phase}
                      </span>
                      {isActive && (
                        <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse flex-shrink-0" />
                      )}
                      {isSelected && (
                        <span className="ml-auto w-1 h-1 rounded-full bg-blue-500 flex-shrink-0" />
                      )}
                    </div>
                    <div className={`text-[10px] truncate leading-tight ${isSelected ? colors.text : 'text-slate-500'}`}>
                      {phaseName}
                    </div>
                  </div>
                  <div className="flex flex-col items-end gap-0.5 ml-1 flex-shrink-0">
                    {isSkipped ? (
                      <span className="text-[9px] text-slate-400 bg-slate-100 px-1 rounded">
                        {isBypassed ? 'SKIP' : 'N/A'}
                      </span>
                    ) : duration !== null ? (
                      <span className={`text-[9px] font-mono font-semibold ${isSelected ? colors.text : 'text-blue-700'}`}>
                        {fmtDuration(duration)}
                      </span>
                    ) : null}
                    {!isSkipped && (
                      <button
                        onClick={(e) => { void togglePhaseEnabled(phase.phase, e); }}
                        title={phaseEnabled[phase.phase] !== false ? 'Phase enabled — click to disable' : 'Phase disabled — click to enable'}
                        className={`flex items-center gap-0.5 px-1 py-0.5 rounded text-[9px] font-semibold transition-all ${
                          savingPhase === phase.phase
                            ? 'opacity-50 bg-slate-100 text-slate-400'
                            : phaseEnabled[phase.phase] !== false
                              ? 'bg-emerald-50 border border-emerald-200 text-emerald-700 hover:bg-emerald-100'
                              : 'bg-slate-100 border border-slate-200 text-slate-400 hover:bg-slate-200'
                        }`}
                      >
                        <span className={`w-1 h-1 rounded-full ${phaseEnabled[phase.phase] !== false ? 'bg-emerald-500' : 'bg-slate-400'}`} />
                        {phaseEnabled[phase.phase] !== false ? 'ON' : 'OFF'}
                      </button>
                    )}
                  </div>
                </button>
              );
            })}
        </div>
      </aside>

      {/* ── Main content ────────────────────────────────────────────────── */}
      <div className="flex-1 min-w-0 p-6 space-y-4">

        {phaseChanged && (
          <div className="flex items-center justify-between gap-3 px-3 py-2 rounded-lg border border-amber-300 bg-amber-50 text-amber-800 text-xs font-medium">
            <span>⚠️ Phase settings saved. Restart Spiral for changes to take effect.</span>
            <button onClick={() => setPhaseChanged(false)} className="text-amber-500 hover:text-amber-700 font-bold text-sm leading-none">✕</button>
          </div>
        )}

        {/* Timestamps */}
        <div className="flex items-center justify-between">
          <div className="text-[10px] text-slate-400">Timestamps shown in Malaysia Time (MYT, UTC+8)</div>
          <div className="text-[10px] text-slate-400">Now: {new Date().toLocaleString('en-MY', { timeZone: 'Asia/Kuala_Lumpur', hour12: false })}</div>
        </div>

        {traceData.phaseOutputs.checkpoint && (
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <span className="font-medium">Checkpoint:</span>
            <span>Iteration {traceData.phaseOutputs.checkpoint.iter}, Phase {traceData.phaseOutputs.checkpoint.phase}</span>
            {traceData.phaseOutputs.checkpoint.ts && (
              <span className="text-slate-400">({formatMYT(traceData.phaseOutputs.checkpoint.ts)} · {timeAgo(traceData.phaseOutputs.checkpoint.ts)})</span>
            )}
          </div>
        )}

        {/* Iteration timing summary */}
        {(iterStartTs || iterEndTs) && (
          <div className="flex items-center gap-4 text-[11px] text-slate-500 bg-white/60 rounded-lg border border-slate-200 px-3 py-2">
            {iterStartTs && <span>Started: <span className="font-mono font-medium text-slate-700">{formatMYT(iterStartTs)}</span></span>}
            {iterEndTs && <span>Finished: <span className="font-mono font-medium text-slate-700">{formatMYT(iterEndTs)}</span></span>}
            {iterTotalDuration !== null && <span>Duration: <span className="font-mono font-semibold text-blue-700">{fmtDuration(iterTotalDuration)}</span></span>}
          </div>
        )}

        {/* ── Phase detail panel or empty state ── */}
        {(() => {
          if (!selectedPhaseNavKey) {
            return (
              <div className="flex flex-col items-center justify-center py-16 gap-3 text-center">
                <span className="text-4xl">🔬</span>
                <div>
                  <div className="text-sm font-medium text-slate-500">Select a phase</div>
                  <div className="text-xs text-slate-400 mt-1">Click any phase in the left sidebar to view its details and logs</div>
                </div>
              </div>
            );
          }

          const sortedPhases = currentIter.phases
            .filter(p => p.phase !== 'G')
            .sort((a, b) => (PHASE_ORDER[a.phase] ?? 99) - (PHASE_ORDER[b.phase] ?? 99));
          const phase = sortedPhases.find(p => p.phase === selectedPhaseNavKey);
          if (!phase) return <div className="text-sm text-slate-400">Phase not found</div>;

          const colors = PHASE_COLORS[phase.phase] ?? { bg: 'bg-slate-50', border: 'border-slate-200', text: 'text-slate-700', dot: 'bg-slate-400' };
          const phaseName = PHASE_NAMES[phase.phase] ?? `Phase ${phase.phase}`;
          const duration = getDuration(phase.phase);
          const startTs = getStartTs(phase.phase);
          const endTs = getEndTs(phase.phase);
          const summary = outputSummary(phase.phase);
          const key = selectedPhaseNavKey;
          const substeps: Substep[] = (phase as IterPhase & { substeps?: Substep[] }).substeps ?? [];
          const hasSubsteps = substeps.length > 0;
          const isBypassed = phase.bypassed === true;
          const isNotYetRun = !isBypassed && (phase.label.endsWith('(not run)') || phase.lineStart === -1);
          const isSkipped = isBypassed || isNotYetRun;

          return (
            <div className={`rounded-xl border ${isSkipped ? 'border-slate-200 bg-slate-50/50' : `${colors.border} ${colors.bg}`} overflow-hidden`}>
              {/* Phase header */}
              <div className={`flex items-center gap-3 px-4 py-3 border-b ${isSkipped ? 'border-slate-200' : `${colors.border} bg-white/30`}`}>
                <div className={`w-3 h-3 rounded-full ${colors.dot} flex-shrink-0`} />
                <span className={`text-sm font-bold font-mono ${colors.text}`}>Phase {phase.phase}</span>
                <span className={`text-sm font-semibold ${colors.text}`}>{phaseName}</span>
                {phase.label && phase.label !== phaseName && !isSkipped && (
                  <span className="text-xs text-slate-500 truncate">{phase.label}</span>
                )}
                {phase.phase === 'I' && !isSkipped && activeStory?.storyId && (
                  <span className="flex items-center gap-1.5 text-[10px] font-medium bg-amber-50 border border-amber-200 text-amber-700 px-2 py-0.5 rounded-full flex-shrink-0">
                    <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
                    {activeStory.storyId}
                    {activeStory.title && <span className="text-amber-600 truncate max-w-[140px]">{activeStory.title}</span>}
                  </span>
                )}
                <div className="ml-auto flex items-center gap-2 flex-shrink-0">
                  {isBypassed && <span className="text-[10px] text-slate-500 bg-slate-200 px-2 py-0.5 rounded-full font-medium">BYPASSED</span>}
                  {isNotYetRun && <span className="text-[10px] text-slate-400 bg-slate-100 px-2 py-0.5 rounded-full font-medium">NOT YET RUN</span>}
                  {!isSkipped && summary && <span className="text-[10px] text-slate-500 bg-white/60 px-2 py-0.5 rounded-full">{summary}</span>}
                  {!isSkipped && hasSubsteps && <span className="text-[10px] text-slate-500 bg-white/60 px-2 py-0.5 rounded-full">{substeps.length} steps</span>}
                  {!isSkipped && duration !== null && (
                    <span className="text-[10px] font-mono font-semibold text-blue-700 bg-blue-50 border border-blue-200 px-2 py-0.5 rounded-full">
                      {fmtDuration(duration)}
                    </span>
                  )}
                  {!isSkipped && endTs && (
                    <span className="text-[10px] font-mono text-slate-500 bg-white/60 px-2 py-0.5 rounded-full" title={`Completed: ${formatMYT(endTs)}`}>
                      {fmtTime(endTs)}
                    </span>
                  )}
                  {!isSkipped && <span className="text-[10px] text-slate-400">{phase.lines.length} lines</span>}
                </div>
              </div>

              {/* Phase detail body */}
              {!isSkipped && (
                <div>
                  {/* Story IDs mentioned in this phase */}
                  {(() => {
                    if (!stories || stories.length === 0) return null;
                    const stripAnsi = (s: string) => s.replace(/\x1b\[[0-9;]*[mGKHFJ]/g, '').replace(/\u001b\[[0-9;]*[mGKHFJ]/g, '');
                    const ids = new Set<string>();
                    for (const line of phase.lines) {
                      const m = stripAnsi(line).match(/(?:US|UT)-\d+/gi) ?? [];
                      for (const id of m) ids.add(id.toUpperCase());
                    }
                    if (ids.size === 0) return null;
                    const passed = [...ids].filter(id => stories.find(s => s.id === id)?.passes === true);
                    const pending = [...ids].filter(id => {
                      const s = stories.find(st => st.id === id);
                      return s && s.passes !== true;
                    });
                    const unknown = [...ids].filter(id => !stories.find(s => s.id === id));
                    return (
                      <div className="px-4 py-2 border-b border-slate-200/50 bg-white/40 flex flex-wrap items-center gap-1.5">
                        <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mr-1">Stories:</span>
                        {passed.map(id => (
                          <span key={id} className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold bg-emerald-100 text-emerald-700 border border-emerald-200">
                            ✓ {id}
                          </span>
                        ))}
                        {pending.map(id => (
                          <span key={id} className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold bg-amber-50 text-amber-700 border border-amber-200">
                            ○ {id}
                          </span>
                        ))}
                        {unknown.map(id => (
                          <span key={id} className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-[10px] font-mono text-slate-400 bg-slate-50 border border-slate-200">
                            {id}
                          </span>
                        ))}
                      </div>
                    );
                  })()}
                  {/* Timing detail */}
                  {(startTs || endTs || duration !== null) && (
                    <div className="flex items-center gap-4 px-4 py-2 text-[11px] text-slate-500 bg-white/50 border-b border-slate-200/50">
                      {startTs && <span>Start: <span className="font-mono font-medium text-slate-700">{formatMYT(startTs)}</span></span>}
                      {endTs && <span>End: <span className="font-mono font-medium text-slate-700">{formatMYT(endTs)}</span></span>}
                      {duration !== null && <span>Duration: <span className="font-mono font-semibold text-blue-700">{fmtDuration(duration)}</span></span>}
                    </div>
                  )}
                  {/* Phase I — Metrics Dashboard */}
                  {phase.phase === 'I' && (() => {
                    const m = extractPhaseIMetrics(phase.lines);
                    const hasData = m.storyBudgets.length > 0 || m.spawnCount > 0 || m.lastAction;
                    if (!hasData) return null;
                    const baseNum   = m.baselineTests ? parseInt(m.baselineTests) : null;
                    const latestNum = m.latestTests   ? parseInt(m.latestTests)   : null;
                    const testColor = baseNum !== null && latestNum !== null
                      ? (latestNum >= baseNum ? 'text-emerald-600' : 'text-red-600')
                      : 'text-slate-700';
                    return (
                      <div className="px-4 py-3 border-b border-emerald-200/60 bg-emerald-50/70">
                        <div className="text-[10px] font-semibold text-emerald-700 uppercase tracking-wider mb-2.5">Phase I — Live Metrics</div>
                        <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-[11px]">
                          {/* Spawns / Undos */}
                          <div className="flex items-center gap-2">
                            <span className="text-slate-500 w-20 flex-shrink-0">Spawns:</span>
                            <span className="font-mono font-bold text-slate-700">{m.spawnCount}</span>
                            {m.undoCount > 0 && <span className="text-amber-600 font-mono text-[10px] bg-amber-50 border border-amber-200 rounded px-1">{m.undoCount} undo</span>}
                          </div>
                          {/* Tests */}
                          <div className="flex items-center gap-2">
                            <span className="text-slate-500 w-20 flex-shrink-0">Tests:</span>
                            {m.baselineTests && <span className="font-mono text-slate-400">{m.baselineTests} →</span>}
                            {latestNum !== null && <span className={`font-mono font-bold ${testColor}`}>{latestNum}</span>}
                            {m.latestFailing && parseInt(m.latestFailing) > 0 && (
                              <span className="font-mono font-bold text-red-600 bg-red-50 border border-red-200 rounded px-1">⚠ {m.latestFailing} failing</span>
                            )}
                            {!m.latestTests && <span className="text-slate-400">—</span>}
                          </div>
                          {/* Stories attempted */}
                          {m.storyBudgets.length > 0 && (
                            <div className="col-span-2 flex items-start gap-2">
                              <span className="text-slate-500 w-20 flex-shrink-0 pt-0.5">Stories:</span>
                              <div className="flex flex-wrap gap-1">
                                {m.storyBudgets.map((s, i) => (
                                  <span key={i} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-mono bg-emerald-100 text-emerald-700 border border-emerald-200">
                                    {s.id} <span className="text-emerald-500">{s.budget}s</span>
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}
                          {/* Last action */}
                          {m.lastAction && (
                            <div className="col-span-2 flex items-start gap-2">
                              <span className="text-slate-500 w-20 flex-shrink-0 pt-0.5">Last action:</span>
                              <span className="font-mono text-slate-600 text-[10px] break-all">{m.lastAction}</span>
                            </div>
                          )}
                          {/* Stash warning */}
                          {m.stashed && (
                            <div className="col-span-2 flex items-center gap-1.5 text-[10px] text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
                              ⚠ Working tree was auto-stashed before implementation
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })()}

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
                              <div className="border-t border-slate-800 bg-slate-950">
                                <div className="flex items-center justify-end px-2 py-1 bg-slate-900 border-b border-slate-800">
                                  {(() => {
                                    const subCopyKey = `sub-${key}-${si}`;
                                    const subCopied = copiedKey === subCopyKey;
                                    return (
                                      <button
                                        onClick={() => {
                                          void navigator.clipboard.writeText(sub.lines.map(l => processLogLine(l, startTs ? new Date(startTs) : null)).join('\n'));
                                          setCopiedKey(subCopyKey);
                                          setTimeout(() => setCopiedKey(prev => prev === subCopyKey ? null : prev), 2000);
                                        }}
                                        title="Copy log to clipboard"
                                        className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono transition-all ${
                                          subCopied ? 'bg-emerald-600 text-white' : 'bg-slate-700 hover:bg-slate-600 text-slate-300'
                                        }`}
                                      >
                                        {subCopied ? '✓ Copied' : '⎘ Copy'}
                                      </button>
                                    );
                                  })()}
                                </div>
                                <div className="overflow-auto max-h-[250px]">
                                  <pre className="p-2.5 text-[10px] text-slate-300 font-mono leading-relaxed whitespace-pre-wrap">
                                    {sub.lines.map(l => processLogLine(l, startTs ? new Date(startTs) : null)).join('\n')}
                                  </pre>
                                </div>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* Full phase log output */}
                  {(() => {
                    const phaseBaseDate = startTs ? new Date(startTs) : null;
                    const isMaximized = maximizedPhase === key;
                    const processed = phase.lines.map(l => processLogLine(l, phaseBaseDate));
                    const phaseCopyKey = `phase-${key}`;
                    const phaseCopied = copiedKey === phaseCopyKey;
                    const toolbar = (
                      <div className="flex items-center justify-between px-3 py-1.5 border-b border-slate-800 bg-slate-900">
                        <span className="text-[10px] text-slate-500 font-mono">
                          {phase.lines.length} lines{phase.phase === 'I' ? ' · elapsed→MYT' : ''}
                          {isMaximized && <span className="ml-2 text-blue-400">Phase {phase.phase} — {PHASE_NAMES[phase.phase] ?? phase.phase}</span>}
                        </span>
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => setMaximizedPhase(prev => prev === key ? null : key)}
                            title={isMaximized ? 'Restore to inline (Esc)' : 'Maximize to fullscreen'}
                            className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono transition-all ${
                              isMaximized ? 'bg-blue-600 text-white' : 'bg-slate-700 hover:bg-slate-600 text-slate-300'
                            }`}
                          >
                            {isMaximized ? '⊡ Restore' : '⊞ Max'}
                          </button>
                          <button
                            onClick={() => {
                              void navigator.clipboard.writeText(processed.join('\n'));
                              setCopiedKey(phaseCopyKey);
                              setTimeout(() => setCopiedKey(prev => prev === phaseCopyKey ? null : prev), 2000);
                            }}
                            title="Copy log to clipboard"
                            className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono transition-all ${
                              phaseCopied ? 'bg-emerald-600 text-white' : 'bg-slate-700 hover:bg-slate-600 text-slate-300'
                            }`}
                          >
                            {phaseCopied ? '✓ Copied' : '⎘ Copy'}
                          </button>
                        </div>
                      </div>
                    );
                    const logBody = (
                      <div className={`overflow-auto ${isMaximized ? 'flex-1' : 'max-h-[500px]'}`}>
                        <pre className="p-3 text-[11px] text-slate-300 font-mono leading-relaxed whitespace-pre-wrap">
                          {processed.join('\n')}
                        </pre>
                      </div>
                    );
                    if (isMaximized) {
                      return createPortal(
                        <div className="fixed inset-0 z-[9999] bg-slate-950 flex flex-col">
                          {toolbar}
                          {logBody}
                        </div>,
                        document.body
                      );
                    }
                    return (
                      <div className="bg-slate-950">
                        {toolbar}
                        {logBody}
                      </div>
                    );
                  })()}
                </div>
              )}
            </div>
          );
        })()}

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
              const isSelected = selectedOutputFile === item.key;
              const isClickable = !!data;
              return (
                <button
                  key={item.key}
                  disabled={!isClickable}
                  onClick={() => setSelectedOutputFile(isSelected ? null : item.key)}
                  className={`rounded-lg border px-3 py-2 flex items-center justify-between text-left w-full transition-all
                    ${colors.border} ${colors.bg}
                    ${isClickable ? 'cursor-pointer hover:brightness-95 active:scale-[0.99]' : 'cursor-default opacity-60'}
                    ${isSelected ? 'ring-2 ring-offset-1 ring-blue-400' : ''}
                  `}
                >
                  <div className="flex items-center gap-2">
                    <div className={`w-2 h-2 rounded-full ${colors.dot}`} />
                    <span className={`text-xs font-medium ${colors.text}`}>{item.label}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className={`text-xs font-mono ${count > 0 ? colors.text : 'text-slate-400'}`}>
                      {data ? `${count} stories` : 'N/A'}
                    </span>
                    {isClickable && (
                      <span className={`text-[10px] text-slate-400 transition-transform ${isSelected ? 'rotate-180' : ''}`}>▼</span>
                    )}
                  </div>
                </button>
              );
            })}
          </div>

          {/* Expandable detail panel */}
          {selectedOutputFile && (() => {
            const panelKey = selectedOutputFile;
            const panelData = traceData.phaseOutputs[panelKey] as { stories?: OutputFileStory[] } | null;
            const panelStories = panelData?.stories ?? [];
            const filePath = OUTPUT_FILE_PATHS[panelKey as string] ?? panelKey;
            return (
              <div className="mt-3 rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
                {/* Panel header */}
                <div className="flex items-center justify-between px-4 py-2.5 bg-slate-50 border-b border-slate-200">
                  <div className="flex items-center gap-3 min-w-0">
                    <span className="text-xs font-semibold text-slate-700">{panelStories.length} {panelStories.length === 1 ? 'story' : 'stories'}</span>
                    <code className="text-[11px] font-mono text-slate-500 truncate">{filePath}</code>
                  </div>
                  <button
                    onClick={() => setSelectedOutputFile(null)}
                    className="text-slate-400 hover:text-slate-600 text-xs leading-none ml-3 flex-shrink-0"
                    aria-label="Close panel"
                  >
                    ✕
                  </button>
                </div>

                {panelStories.length === 0 ? (
                  <div className="px-4 py-4 text-xs text-slate-400 italic">No stories in this file.</div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs border-collapse">
                      <thead>
                        <tr className="bg-slate-50 text-left text-[11px] text-slate-500 uppercase tracking-wide">
                          <th className="px-3 py-2 font-semibold w-[100px]">ID</th>
                          <th className="px-3 py-2 font-semibold">Title</th>
                          <th className="px-3 py-2 font-semibold w-[90px]">Priority</th>
                          <th className="px-3 py-2 font-semibold w-[110px]">Source</th>
                        </tr>
                      </thead>
                      <tbody>
                        {panelStories.map((s, idx) => {
                          const sid = s.id ?? `#${idx + 1}`;
                          const title = s.title ?? '—';
                          const priority = typeof s.priority === 'string' ? s.priority : null;
                          const source = typeof s._source === 'string' ? s._source : null;
                          return (
                            <tr key={sid} className="border-t border-slate-100 hover:bg-slate-50 transition-colors">
                              <td className="px-3 py-2 font-mono text-[11px] text-blue-700 whitespace-nowrap">{sid}</td>
                              <td className="px-3 py-2 text-slate-700 leading-snug">{title}</td>
                              <td className="px-3 py-2">
                                {priority ? (
                                  <span className={`inline-block text-[10px] px-1.5 py-0.5 rounded-full border font-medium ${PRIORITY_BADGE[priority] ?? 'bg-slate-100 text-slate-500 border-slate-200'}`}>
                                    {priority}
                                  </span>
                                ) : <span className="text-slate-300">—</span>}
                              </td>
                              <td className="px-3 py-2">
                                {source ? (
                                  <span className={`inline-block text-[10px] px-1.5 py-0.5 rounded-full border font-medium ${SOURCE_COLORS[source] ?? 'bg-slate-100 text-slate-500 border-slate-200'}`}>
                                    {source}
                                  </span>
                                ) : <span className="text-slate-300">—</span>}
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
          })()}
        </div>
      </div>
    </div>
  );
}

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

interface TokenStats {
  total: { input: number; output: number; tokens: number; usd: number };
  avgPerStory: number;
  mostExpensive: { story_id: string; title: string; usd: number } | null;
  byModel: TokenModelRow[];
  byStory: TokenStoryRow[];
  byPhase: TokenPhaseRow[];
  trend: TrendPoint[];
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

const PHASE_FULL_NAMES: Record<string, string> = {
  '0': 'Clarify', A: 'AI Suggestions', R: 'Research', T: 'Test Synthesis',
  S: 'Story Validate', M: 'Merge', I: 'Implement', V: 'Validate',
  P: 'Push', C: 'Check Done', D: 'Loop Decision',
};

function TokenTab({ projectName, tokenBurn }: { projectName: string; tokenBurn?: TokenBurnEntry[] }) {
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
                      <td className="px-3 py-1.5 text-right text-slate-400">{fmtK(e.creation_tokens)}</td>
                      <td className="px-3 py-1.5 text-right text-emerald-600">{fmtK(e.read_tokens)}</td>
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

// ── Tests tab ────────────────────────────────────────────────────────────────

interface TestItem { id: string; cls: string; name: string; }
interface TestFileEntry { name: string; path: string; tests: TestItem[]; }

function TestsTab({ projectName }: { projectName: string }) {
  const [files, setFiles] = useState<TestFileEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [running, setRunning] = useState(false);
  const [output, setOutput] = useState<string | null>(null);
  const [summary, setSummary] = useState<{ passed: number; failed: number; errors: number; total: number } | null>(null);
  const [lastResults, setLastResults] = useState<Record<string, 'passed' | 'failed' | 'error'>>({});
  const outputRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    fetch(`/api/tests?name=${encodeURIComponent(projectName)}`)
      .then(r => r.json() as Promise<{ files: TestFileEntry[]; total: number; error?: string }>)
      .then(d => {
        if (d.error) setFetchError(d.error);
        else setFiles(d.files ?? []);
        setLoading(false);
      })
      .catch(e => { setFetchError(String(e)); setLoading(false); });
  }, [projectName]);

  useEffect(() => {
    if (outputRef.current) outputRef.current.scrollTop = outputRef.current.scrollHeight;
  }, [output]);

  const totalTests = files.reduce((s, f) => s + f.tests.length, 0);

  const filteredFiles = filter.trim()
    ? files
        .map(f => ({ ...f, tests: f.tests.filter(t => t.id.toLowerCase().includes(filter.toLowerCase()) || t.name.toLowerCase().includes(filter.toLowerCase())) }))
        .filter(f => f.tests.length > 0)
    : files;

  const allFilteredIds = filteredFiles.flatMap(f => f.tests.map(t => t.id));

  const toggleTest = (id: string) => {
    setSelected(prev => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  };
  const toggleFile = (file: TestFileEntry) => {
    const ids = file.tests.map(t => t.id);
    const allSel = ids.every(id => selected.has(id));
    setSelected(prev => { const n = new Set(prev); if (allSel) ids.forEach(id => n.delete(id)); else ids.forEach(id => n.add(id)); return n; });
  };
  const toggleExpanded = (p: string) => {
    setExpanded(prev => { const n = new Set(prev); if (n.has(p)) n.delete(p); else n.add(p); return n; });
  };

  const runTests = async () => {
    setRunning(true);
    setOutput(null);
    setSummary(null);
    try {
      const testIds = selected.size > 0 ? Array.from(selected) : [];
      const res = await fetch('/api/run-tests', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: projectName, testIds }),
      });
      type RunResult = { output: string; passed: number; failed: number; errors: number; total: number; testResults: Record<string, string>; error?: string };
      const data = await res.json() as RunResult;
      if (data.error) {
        setOutput(`Error: ${data.error}`);
      } else {
        setOutput(data.output ?? '');
        setSummary({ passed: data.passed ?? 0, failed: data.failed ?? 0, errors: data.errors ?? 0, total: data.total ?? 0 });
        setLastResults((data.testResults ?? {}) as Record<string, 'passed' | 'failed' | 'error'>);
      }
    } catch (e) {
      setOutput(`Request error: ${String(e)}`);
    } finally {
      setRunning(false);
    }
  };

  if (loading) return <div className="p-6 text-sm text-slate-500">Loading tests…</div>;
  if (fetchError) return <div className="p-6 text-sm text-red-500">Error loading tests: {fetchError}</div>;

  const selCount = selected.size;

  return (
    <div className="h-full flex flex-col">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-slate-200 bg-white flex-shrink-0 flex-wrap">
        <span className="text-xs text-slate-500 font-medium whitespace-nowrap">{totalTests} tests</span>
        <input
          type="text"
          placeholder="Filter tests…"
          value={filter}
          onChange={e => setFilter(e.target.value)}
          className="w-52 border border-slate-300 rounded px-2 py-1 text-xs focus:outline-none focus:border-blue-400"
        />
        <button
          onClick={() => setSelected(new Set(allFilteredIds))}
          className="text-xs px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-600 transition-colors whitespace-nowrap"
        >Select All</button>
        <button
          onClick={() => setSelected(new Set())}
          className="text-xs px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-600 transition-colors"
        >Clear</button>
        <button
          onClick={runTests}
          disabled={running}
          className={`text-xs px-3 py-1 rounded font-semibold transition-colors whitespace-nowrap ${
            running ? 'bg-slate-200 text-slate-400 cursor-not-allowed' : 'bg-blue-600 hover:bg-blue-700 text-white shadow-sm'
          }`}
        >
          {running ? '⏳ Running…' : selCount > 0 ? `▶ Run Selected (${selCount})` : '▶ Run All'}
        </button>
        {summary && (
          <div className="flex items-center gap-2 text-xs">
            {summary.passed > 0 && <span className="text-emerald-600 font-semibold">✓ {summary.passed} passed</span>}
            {summary.failed > 0 && <span className="text-red-600 font-semibold">✗ {summary.failed} failed</span>}
            {summary.errors > 0 && <span className="text-orange-500 font-semibold">! {summary.errors} error</span>}
            <span className="text-slate-400">({summary.total} total)</span>
          </div>
        )}
      </div>

      {/* Split pane */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left: test tree */}
        <div className="w-80 flex-shrink-0 border-r border-slate-200 overflow-y-auto bg-white">
          {filteredFiles.length === 0 && (
            <div className="p-4 text-xs text-slate-400 text-center">No tests match filter</div>
          )}
          {filteredFiles.map(file => {
            const isOpen = expanded.has(file.path);
            const fileSel = file.tests.filter(t => selected.has(t.id)).length;
            const allSel = fileSel === file.tests.length && file.tests.length > 0;
            const partSel = fileSel > 0 && !allSel;
            return (
              <div key={file.path} className="border-b border-slate-100">
                <div
                  className="flex items-center gap-1.5 px-2 py-1.5 hover:bg-slate-50 cursor-pointer select-none"
                  onClick={() => toggleExpanded(file.path)}
                >
                  <input
                    type="checkbox"
                    checked={allSel}
                    ref={el => { if (el) el.indeterminate = partSel; }}
                    onChange={() => toggleFile(file)}
                    onClick={e => e.stopPropagation()}
                    className="w-3 h-3 accent-blue-600 flex-shrink-0"
                  />
                  <span className="text-[10px] text-slate-400 w-3 flex-shrink-0">{isOpen ? '▾' : '▸'}</span>
                  <span className="text-[11px] font-mono font-semibold text-slate-700 truncate flex-1">{file.name}</span>
                  <span className="text-[10px] text-slate-400 flex-shrink-0">{fileSel}/{file.tests.length}</span>
                </div>
                {isOpen && file.tests.map(test => {
                  const result = lastResults[test.id];
                  return (
                    <div
                      key={test.id}
                      className={`flex items-center gap-1.5 pl-7 pr-2 py-0.5 hover:bg-slate-50 cursor-pointer ${selected.has(test.id) ? 'bg-blue-50' : ''}`}
                      onClick={() => toggleTest(test.id)}
                    >
                      <input
                        type="checkbox"
                        checked={selected.has(test.id)}
                        onChange={() => toggleTest(test.id)}
                        onClick={e => e.stopPropagation()}
                        className="w-3 h-3 accent-blue-600 flex-shrink-0"
                      />
                      <span className="w-3 flex-shrink-0 text-[10px] leading-none">
                        {result === 'passed' && <span className="text-emerald-500">✓</span>}
                        {result === 'failed' && <span className="text-red-500">✗</span>}
                        {result === 'error'  && <span className="text-orange-500">!</span>}
                      </span>
                      <span className="text-[11px] font-mono text-slate-600 truncate">{test.name}</span>
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>

        {/* Right: output console */}
        <div className="flex-1 bg-slate-950 overflow-hidden flex flex-col">
          {output === null && !running ? (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center text-slate-500">
                <div className="text-4xl mb-3">🧪</div>
                <div className="text-sm font-medium">No results yet</div>
                <div className="text-xs mt-1 text-slate-600">Select tests and click Run, or click ▶ Run All</div>
              </div>
            </div>
          ) : running ? (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center text-slate-400">
                <div className="text-3xl mb-3">⏳</div>
                <div className="text-sm">Running tests…</div>
                <div className="text-xs mt-1 text-slate-600">This may take a while for large suites</div>
              </div>
            </div>
          ) : (
            <pre
              ref={outputRef}
              className="flex-1 overflow-y-auto p-4 text-[11px] font-mono leading-relaxed text-slate-200 whitespace-pre-wrap break-all"
            >
              {output}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

type DashTab = 'progress' | 'settings' | 'constitution' | 'skills' | 'activity' | 'graph' | 'phase-trace' | 'workers' | 'tokens' | 'tests' | 'analytics';

const DASH_TABS: { id: DashTab; slug: string; label: string; icon: string }[] = [
  { id: 'progress',     slug: 'progress',     label: 'Progress',     icon: '📊' },
  { id: 'phase-trace',  slug: 'phase-trace',  label: 'Phase Trace',  icon: '🔬' },
  { id: 'workers',      slug: 'workers',      label: 'Workers',      icon: '👷' },
  { id: 'tokens',       slug: 'tokens',       label: 'Tokens',       icon: '💰' },
  { id: 'graph',        slug: 'graph',        label: 'Graph',        icon: '🔗' },
  { id: 'tests',        slug: 'tests',        label: 'Tests',        icon: '🧪' },
  { id: 'settings',     slug: 'settings',     label: 'Settings',     icon: '⚙️' },
  { id: 'constitution', slug: 'constitution', label: 'Constitution', icon: '📜' },
  { id: 'skills',       slug: 'skills',       label: 'Skills',       icon: '🎯' },
  { id: 'activity',     slug: 'activity',     label: 'Activity Log', icon: '📝' },
  { id: 'analytics',    slug: 'analytics',    label: 'Analytics',    icon: '📈' },
];

const VALID_TABS = new Set(DASH_TABS.map(t => t.slug));

export default function ProjectDashboard() {
  const { projectName, tab } = useParams<{ projectName: string; tab?: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<ProjectData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [activeStory, setActiveStory] = useState<ActiveStoryInfo | null>(null);

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

  const loadActiveStory = useCallback(async () => {
    try {
      const res = await fetch(`/api/active-story?name=${encodeURIComponent(projectName ?? '')}`);
      if (res.ok) {
        const d = await res.json() as { storyId: string | null; title?: string | null };
        setActiveStory({ storyId: d.storyId, title: d.title ?? null });
      }
    } catch { /* ignore */ }
  }, [projectName]);

  useEffect(() => {
    load();
    const interval = setInterval(load, 5_000); // refresh every 5s for live status banner (US-315)
    return () => clearInterval(interval);
  }, [load]);

  useEffect(() => {
    loadActiveStory();
    const interval = setInterval(loadActiveStory, 15_000); // poll active story every 15s
    return () => clearInterval(interval);
  }, [loadActiveStory]);

  // US-374: SSE subscription for real-time phase and story event streaming.
  // On phase_start/phase_end events, update activeStatus immediately for sub-second
  // UI feedback, then trigger a debounced full data reload for consistency.
  const sseRefreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handleSSEEvent = useCallback((evt: SSEEvent) => {
    const eventName = evt.event_type ?? evt.event ?? evt.type ?? '';
    if (eventName === 'phase_start' || eventName === 'phase_end') {
      // Immediately update activeStatus in data for instant phase indicator update
      setData(prev => {
        if (!prev) return prev;
        return {
          ...prev,
          activeStatus: eventName === 'phase_start'
            ? {
                phase: (evt.phase as string) ?? prev.activeStatus?.phase ?? '',
                iteration: (evt.iteration as number) ?? prev.activeStatus?.iteration ?? 0,
                started_at: Date.now(),
                pct_done: 0,
                story_id: (evt.story_id as string) ?? prev.activeStatus?.story_id,
                story_title: (evt.story_title as string) ?? prev.activeStatus?.story_title,
              }
            : prev.activeStatus, // phase_end: keep current until full refresh
        };
      });
      // Debounced full reload (500ms) so rapid events don't flood the server
      if (sseRefreshTimer.current) clearTimeout(sseRefreshTimer.current);
      sseRefreshTimer.current = setTimeout(() => { load(); loadActiveStory(); }, 500);
    } else if (eventName === 'story_passed' || eventName === 'story_failed') {
      // Story completion: trigger full reload for updated progress stats
      if (sseRefreshTimer.current) clearTimeout(sseRefreshTimer.current);
      sseRefreshTimer.current = setTimeout(() => { load(); loadActiveStory(); }, 500);
    }
  }, [load, loadActiveStory]);
  useSSE(projectName, handleSSEEvent);

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
    // Active status is the strongest signal — written by SPIRAL during phase execution
    if (data.activeStatus) return true;
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

      {/* US-315: Live status banner */}
      <LiveStatusBanner
        activeStatus={data.activeStatus}
        lastCompletedStory={data.lastCompletedStory}
        checkpointTs={data.checkpointTs}
        lastLogModified={data.lastLogModified}
        isRunning={isRunning}
      />

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
        {activeTab === 'progress'     && <div className="h-full overflow-y-auto"><ProgressTab data={data} projectName={projectName ?? ''} onRefresh={load} activeStory={activeStory} /></div>}
        {activeTab === 'phase-trace'  && <div className="h-full overflow-y-auto"><PhaseTraceTab projectName={projectName ?? ''} stories={data.progress?.stories ?? []} activeStory={activeStory} /></div>}
        {activeTab === 'workers'      && <div className="h-full overflow-y-auto"><WorkersTab projectName={projectName ?? ''} activeStory={activeStory} /></div>}
        {activeTab === 'tokens'       && <div className="h-full overflow-y-auto"><TokenTab projectName={projectName ?? ''} tokenBurn={data.tokenBurn} /></div>}
        {activeTab === 'graph'        && (
          <div className="h-full overflow-hidden">
            <DependencyGraph stories={data.progress?.stories ?? []} storyAttempts={data.storyAttempts} />
          </div>
        )}
        {activeTab === 'settings'     && <div className="h-full overflow-y-auto"><SettingsTab config={data.config} configRaw={data.configRaw ?? ''} projectName={projectName ?? ''} onConfigSaved={() => load()} /></div>}
        {activeTab === 'constitution' && <div className="h-full overflow-y-auto flex flex-col"><ConstitutionTab text={data.constitution} projectName={projectName ?? undefined} /></div>}
        {activeTab === 'skills'       && <div className="h-full overflow-hidden"><SkillsTab projectName={projectName ?? undefined} /></div>}
        {activeTab === 'activity'     && <div className="h-full overflow-y-auto"><ActivityTab log={data.activity} activeStory={activeStory} /></div>}
        {activeTab === 'tests'        && <div className="h-full overflow-hidden"><TestsTab projectName={projectName ?? ''} /></div>}
        {activeTab === 'analytics'    && <div className="h-full overflow-y-auto"><AnalyticsTab projectName={projectName ?? ''} /></div>}
      </main>
    </div>
  );
}
