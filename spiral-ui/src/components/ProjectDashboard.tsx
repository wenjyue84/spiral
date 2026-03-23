import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { useSSE, type SSEEvent } from '../hooks/useSSE';
import { timeAgo } from './StoryDetailPanel';
import DependencyGraph from './DependencyGraph';
import AnalyticsTab from './AnalyticsTab';
import PhaseTraceTab from './PhaseTraceTab';
import TokenTab from './TokenTab';
import WorkersTab from './WorkersTab';
import LiveStatusBanner from './dashboard/LiveStatusBanner';
import ProgressTab from './dashboard/ProgressTab';
import SettingsTab from './dashboard/SettingsTab';
import ConstitutionTab from './dashboard/ConstitutionTab';
import SkillsTab from './dashboard/SkillsTab';
import ActivityTab from './dashboard/ActivityTab';
import TestsTab from './dashboard/TestsTab';
import { type ProjectData, type ActiveStoryInfo, pct } from './dashboard/types';

// Re-exports for backward compatibility
export type { Story, TokenBurnEntry, ActiveStoryInfo } from './dashboard/types';
export { PHASE_LABELS } from './dashboard/LiveStatusBanner';
export { default as ActiveStoryBanner } from './dashboard/ActiveStoryBanner';

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
