import { useState } from 'react';
import { timeAgo, formatMYT } from '../StoryDetailPanel';
import type { LastCompletedStory } from './types';

export default function RecentlyCompletedFeed({ entries, onStoryClick }: { entries?: LastCompletedStory[]; onStoryClick?: (id: string) => void }) {
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
