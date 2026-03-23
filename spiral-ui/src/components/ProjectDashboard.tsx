import { useState, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useParams, Link, useNavigate } from 'react-router-dom';
import DependencyGraph from './DependencyGraph';
import AnalyticsTab from './AnalyticsTab';
import StoryDetailPanel, { type StoryAttempt, formatMYT, timeAgo } from './StoryDetailPanel';
import { CONFIG_FIELDS } from '../data/configSchema';
import { useSSE, type SSEEvent } from '../hooks/useSSE';
import PhaseTraceTab from './PhaseTraceTab';
import TokenTab from './TokenTab';
import WorkersTab from './WorkersTab';

// Config description lookup for tooltips in Settings tab
const CONFIG_DESCRIPTIONS: Record<string, { label: string; description: string }> = Object.fromEntries(
  CONFIG_FIELDS.map(f => [f.key, { label: f.label, description: f.description }])
);
void CONFIG_DESCRIPTIONS; // used for future tooltip integration

// ── Types ────────────────────────────────────────────────────────────────────

export interface Story {
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

export interface TokenBurnEntry {
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

export interface ActiveStoryInfo {
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

function RecentlyCompletedFeed({ entries, onStoryClick }: { entries?: LastCompletedStory[]; onStoryClick?: (id: string) => void }) {
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
            <li key={i} className="flex items-center gap-3 px-4 py-2.5 hover:bg-slate-50 cursor-pointer" onClick={() => onStoryClick?.(e.id)}>
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
export const PHASE_LABELS: Record<string, string> = {
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

export function ActiveStoryBanner({ activeStory, className }: { activeStory: ActiveStoryInfo | null; className?: string }) {
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

interface ConstitutionVersion {
  sha: string;
  shortSha: string;
  date: string;
  relativeDate: string;
  subject: string;
  author: string;
}

function ConstitutionTab({ text, projectName }: { text: string; projectName?: string }) {
  const [draft, setDraft] = useState(text);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');

  // Version history state
  const [versions, setVersions] = useState<ConstitutionVersion[]>([]);
  const [selectedSha, setSelectedSha] = useState<string | null>(null); // null = current/live
  const [versionContent, setVersionContent] = useState('');
  const [loadingVersion, setLoadingVersion] = useState(false);
  const [versionsLoaded, setVersionsLoaded] = useState(false);

  useEffect(() => { setDraft(text); }, [text]);

  // Fetch version history on mount
  useEffect(() => {
    if (versionsLoaded) return;
    (async () => {
      try {
        const res = await fetch(`/api/constitution-versions?name=${encodeURIComponent(projectName ?? '')}`);
        const data = await res.json() as { versions: ConstitutionVersion[] };
        setVersions(data.versions ?? []);
      } catch { /* ignore */ }
      setVersionsLoaded(true);
    })();
  }, [projectName, versionsLoaded]);

  // Fetch content when a historical version is selected
  useEffect(() => {
    if (!selectedSha) { setVersionContent(''); return; }
    let cancelled = false;
    setLoadingVersion(true);
    (async () => {
      try {
        const res = await fetch(`/api/constitution-version?name=${encodeURIComponent(projectName ?? '')}&sha=${encodeURIComponent(selectedSha)}`);
        const data = await res.json() as { content: string };
        if (!cancelled) setVersionContent(data.content ?? '');
      } catch { /* ignore */ }
      if (!cancelled) setLoadingVersion(false);
    })();
    return () => { cancelled = true; };
  }, [selectedSha, projectName]);

  if (!text && draft === '' && versions.length === 0) {
    return (
      <div className="p-6 text-slate-500">
        No constitution found. Set <code className="bg-slate-100 px-1 rounded">SPIRAL_SPECKIT_CONSTITUTION</code> in your config,
        or create <code className="bg-slate-100 px-1 rounded">.specify/memory/constitution.md</code> in your project root.
      </div>
    );
  }

  const isViewingHistory = selectedSha !== null;
  const displayText = isViewingHistory ? versionContent : draft;
  const lineCount = displayText.split('\n').length;
  const isTooLong = !isViewingHistory && lineCount > 150;
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
      setVersionsLoaded(false); // refresh version list after save
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  function handleRestore() {
    if (!versionContent) return;
    setDraft(versionContent);
    setSelectedSha(null);
  }

  return (
    <div className="flex h-full">
      {/* Left sidebar — version history */}
      <div className="w-56 shrink-0 border-r border-slate-200 bg-slate-50 flex flex-col">
        <div className="px-3 py-2.5 border-b border-slate-200 bg-white">
          <span className="text-xs font-semibold text-slate-600 uppercase tracking-wide">Versions</span>
          <span className="ml-1.5 text-[10px] text-slate-400">{versions.length}</span>
        </div>
        <div className="flex-1 overflow-y-auto">
          {/* Current / live entry */}
          <button
            onClick={() => setSelectedSha(null)}
            className={`w-full text-left px-3 py-2 border-b border-slate-100 transition-colors ${
              !isViewingHistory
                ? 'bg-blue-50 border-l-2 border-l-blue-500'
                : 'hover:bg-slate-100 border-l-2 border-l-transparent'
            }`}
          >
            <div className="flex items-center gap-1.5">
              <span className={`w-2 h-2 rounded-full ${isDirty ? 'bg-amber-400' : 'bg-green-400'}`} />
              <span className="text-xs font-semibold text-slate-800">Current</span>
            </div>
            <div className="text-[10px] text-slate-400 mt-0.5">{isDirty ? 'unsaved changes' : 'live version'}</div>
          </button>

          {/* Historical versions */}
          {versions.map(v => (
            <button
              key={v.sha}
              onClick={() => setSelectedSha(v.sha)}
              className={`w-full text-left px-3 py-2 border-b border-slate-100 transition-colors ${
                selectedSha === v.sha
                  ? 'bg-blue-50 border-l-2 border-l-blue-500'
                  : 'hover:bg-slate-100 border-l-2 border-l-transparent'
              }`}
            >
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] font-mono text-slate-500">{v.shortSha}</span>
                <span className="text-[10px] text-slate-400">{v.relativeDate}</span>
              </div>
              <div className="text-[11px] text-slate-700 mt-0.5 line-clamp-2 leading-tight">{v.subject}</div>
            </button>
          ))}

          {versions.length === 0 && versionsLoaded && (
            <div className="px-3 py-4 text-[11px] text-slate-400 text-center">No git history found</div>
          )}
        </div>
      </div>

      {/* Right content area — editor or read-only viewer */}
      <div className="flex-1 flex flex-col overflow-hidden p-6 gap-3">
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-500 font-mono">{lineCount} lines</span>
          {isViewingHistory && (
            <span className="flex items-center gap-1 text-xs font-medium text-blue-700 bg-blue-50 border border-blue-200 rounded px-2 py-0.5">
              Viewing {versions.find(v => v.sha === selectedSha)?.shortSha} — {versions.find(v => v.sha === selectedSha)?.relativeDate}
            </span>
          )}
          {isTooLong && (
            <span className="flex items-center gap-1 text-xs font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-0.5">
              Constitution is long ({lineCount} lines). Consider trimming — LLMs may not reliably follow rules past ~150 lines.
            </span>
          )}
          <div className="ml-auto flex items-center gap-2">
            {error && <span className="text-xs text-red-600">{error}</span>}
            {saved && <span className="text-xs text-green-600 font-medium">Saved</span>}
            {isViewingHistory ? (
              <button
                onClick={handleRestore}
                disabled={loadingVersion || !versionContent}
                className="px-3 py-1 text-xs font-medium rounded transition-colors bg-amber-500 hover:bg-amber-600 text-white disabled:opacity-50"
              >
                Restore this version
              </button>
            ) : (
              <button
                onClick={handleSave}
                disabled={saving || !isDirty}
                className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
                  isDirty
                    ? 'bg-blue-600 hover:bg-blue-700 text-white'
                    : 'bg-slate-100 text-slate-400 cursor-not-allowed'
                }`}
              >
                {saving ? 'Saving...' : 'Save'}
              </button>
            )}
          </div>
        </div>
        {loadingVersion ? (
          <div className="flex-1 flex items-center justify-center text-sm text-slate-400">Loading version...</div>
        ) : (
          <textarea
            value={displayText}
            onChange={isViewingHistory ? undefined : (e => setDraft(e.target.value))}
            readOnly={isViewingHistory}
            className={`flex-1 w-full rounded-xl border p-5 text-xs font-mono leading-relaxed resize-none focus:outline-none focus:ring-2 ${
              isViewingHistory
                ? 'border-slate-200 bg-slate-50 text-slate-600 focus:ring-slate-300 cursor-default'
                : 'border-slate-200 bg-white text-slate-700 focus:ring-blue-300'
            }`}
            spellCheck={false}
            style={{ minHeight: '400px' }}
          />
        )}
      </div>
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
        {activeTab === 'workers'      && <div className="h-full overflow-y-auto"><WorkersTab projectName={projectName ?? ''} activeStory={activeStory} currentPhase={data?.activeStatus?.phase ?? null} isRunning={isRunning} /></div>}
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
