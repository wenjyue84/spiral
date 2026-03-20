import { useState } from 'react';

interface ActivitySection {
  header: string;
  body: string;
}

function ActivityEntry({ entry }: { entry: ActivitySection }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="border border-slate-200 rounded-lg overflow-hidden">
      <button
        className="w-full flex items-center justify-between px-4 py-2.5 bg-white hover:bg-slate-50 text-left transition-colors"
        onClick={() => setOpen(o => !o)}
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-slate-400 text-xs w-3 shrink-0">{open ? '▾' : '▸'}</span>
          <span className="text-xs text-slate-700 font-medium truncate">{entry.header}</span>
        </div>
      </button>

      {open && entry.body && (
        <div className="border-t border-slate-100 bg-slate-50/50 px-4 py-3">
          <pre className="text-[11px] text-slate-600 whitespace-pre-wrap font-mono leading-relaxed">
            {entry.body}
          </pre>
        </div>
      )}
    </div>
  );
}

export default function RecentActivityFeed({ data }: { data: ActivitySection[] }) {
  if (data.length === 0) return null;

  // Show most recent first
  const reversed = [...data].reverse();

  return (
    <div>
      <div className="text-xs font-medium text-slate-500 mb-3 uppercase tracking-wide">
        Recent Activity (last {data.length} iterations)
      </div>
      <div className="space-y-1 max-h-[500px] overflow-y-auto pr-1">
        {reversed.map((entry, i) => (
          <ActivityEntry key={i} entry={entry} />
        ))}
      </div>
    </div>
  );
}
