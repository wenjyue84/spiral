import { timeAgo } from '../StoryDetailPanel';
import type { ActiveStatus, LastCompletedStory } from './types';

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

export default function LiveStatusBanner({ activeStatus, lastCompletedStory, checkpointTs, lastLogModified, isRunning }: {
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
