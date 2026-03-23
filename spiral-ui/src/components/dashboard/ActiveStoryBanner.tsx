import type { ActiveStoryInfo } from './types';

export default function ActiveStoryBanner({ activeStory, className }: { activeStory: ActiveStoryInfo | null; className?: string }) {
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
