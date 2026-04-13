import { useState } from 'react';

interface StoryAttempt {
  timestamp: string; model: string; status: string;
  durationSec: number; retryNum: number; commitSha: string;
  runId: string; inputTokens: number; outputTokens: number;
}

interface StoryEntry {
  id: string; title: string; passes: boolean;
  _decomposed: boolean; _skipped: boolean; _failureReason: string;
  epicId: string; priority: string; source: string;
  attempts: StoryAttempt[];
}

type Filter = 'all' | 'passing' | 'failing' | 'pending';

const STATUS_COLORS: Record<string, string> = {
  keep:   'bg-emerald-100 text-emerald-700',
  revert: 'bg-red-100 text-red-700',
  skip:   'bg-slate-100 text-slate-500',
};

function storyStatus(s: StoryEntry): { label: string; cls: string } {
  if (s.passes)      return { label: 'pass',       cls: 'bg-emerald-100 text-emerald-700 border-emerald-200' };
  if (s._decomposed) return { label: 'decomposed', cls: 'bg-amber-100 text-amber-700 border-amber-200' };
  if (s._skipped)    return { label: 'skipped',    cls: 'bg-slate-100 text-slate-500 border-slate-200' };
  if (s._failureReason) return { label: 'failed',  cls: 'bg-red-100 text-red-600 border-red-200' };
  return { label: 'pending', cls: 'bg-violet-100 text-violet-700 border-violet-200' };
}

function fmtTime(ts: string): string {
  if (!ts) return '-';
  try {
    return new Date(ts).toLocaleString([], { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  } catch { return ts; }
}

function fmtDur(sec: number): string {
  if (!sec) return '-';
  if (sec < 60) return `${sec}s`;
  return `${Math.floor(sec / 60)}m ${sec % 60}s`;
}

function fmtK(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}K` : String(n);
}

function AttemptRow({ a }: { a: StoryAttempt }) {
  const statusCls = STATUS_COLORS[a.status] ?? 'bg-slate-100 text-slate-500';
  const shortSha = a.commitSha ? a.commitSha.slice(0, 7) : '-';
  return (
    <tr className="hover:bg-slate-50">
      <td className="px-3 py-1.5 text-slate-500 whitespace-nowrap">{fmtTime(a.timestamp)}</td>
      <td className="px-3 py-1.5 font-mono text-slate-600 max-w-[140px] truncate" title={a.model}>{a.model || '-'}</td>
      <td className="px-3 py-1.5 text-center">
        <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium ${statusCls}`}>{a.status || '-'}</span>
      </td>
      <td className="px-3 py-1.5 text-right text-slate-600">{fmtDur(a.durationSec)}</td>
      <td className="px-3 py-1.5 text-center text-slate-500">{a.retryNum}</td>
      <td className="px-3 py-1.5 text-right text-slate-400">
        {(a.inputTokens > 0 || a.outputTokens > 0) ? `${fmtK(a.inputTokens)}/${fmtK(a.outputTokens)}` : '-'}
      </td>
      <td className="px-3 py-1.5 font-mono text-slate-400">{shortSha}</td>
    </tr>
  );
}

function StoryRow({ s }: { s: StoryEntry }) {
  const [open, setOpen] = useState(false);
  const { label, cls } = storyStatus(s);

  return (
    <div className="border border-slate-200 rounded-lg overflow-hidden">
      <button
        className="w-full flex items-center justify-between px-4 py-2.5 bg-white hover:bg-slate-50 text-left transition-colors"
        onClick={() => setOpen(o => !o)}
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-slate-400 text-xs w-3 shrink-0">{open ? '▾' : '▸'}</span>
          <span className="font-mono text-xs font-bold text-slate-600 shrink-0">{s.id}</span>
          <span className="text-xs text-slate-600 truncate">{s.title}</span>
        </div>
        <div className="flex items-center gap-2 shrink-0 ml-3">
          {s.attempts.length > 0 && (
            <span className="text-[10px] text-slate-400">{s.attempts.length} attempt{s.attempts.length !== 1 ? 's' : ''}</span>
          )}
          <span className={`inline-block px-2 py-0.5 rounded-full text-[10px] font-medium border ${cls}`}>{label}</span>
        </div>
      </button>

      {open && (
        <div className="border-t border-slate-100 bg-slate-50/50">
          {s._failureReason && (
            <div className="px-4 py-2 text-[11px] text-slate-500 italic border-b border-slate-100">
              {s._failureReason}
            </div>
          )}
          {s.attempts.length === 0 ? (
            <div className="px-4 py-2 text-[11px] text-slate-400 italic">No attempts recorded</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-slate-100 text-slate-500">
                  <tr>
                    <th className="text-left px-3 py-1.5">Timestamp</th>
                    <th className="text-left px-3 py-1.5">Model</th>
                    <th className="text-center px-3 py-1.5">Status</th>
                    <th className="text-right px-3 py-1.5">Duration</th>
                    <th className="text-center px-3 py-1.5">Retry</th>
                    <th className="text-right px-3 py-1.5">In/Out Tokens</th>
                    <th className="text-left px-3 py-1.5">Commit</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {s.attempts.map((a, i) => <AttemptRow key={i} a={a} />)}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function StoriesListAccordion({ data, defaultFilter = 'all' }: { data: StoryEntry[]; defaultFilter?: Filter }) {
  const [filter, setFilter] = useState<Filter>(defaultFilter);
  const [search, setSearch] = useState('');

  const filtered = data.filter(s => {
    if (search) {
      const q = search.toLowerCase();
      if (!s.id.toLowerCase().includes(q) && !s.title.toLowerCase().includes(q)) return false;
    }
    switch (filter) {
      case 'passing': return s.passes;
      case 'failing': return !s.passes && !s._decomposed && !s._skipped && !!s._failureReason;
      case 'pending': return !s.passes && !s._decomposed && !s._skipped && !s._failureReason;
      default: return true;
    }
  });

  const counts = {
    all: data.length,
    passing: data.filter(s => s.passes).length,
    failing: data.filter(s => !s.passes && !s._decomposed && !s._skipped && !!s._failureReason).length,
    pending: data.filter(s => !s.passes && !s._decomposed && !s._skipped && !s._failureReason).length,
  };

  const FILTERS: Array<{ key: Filter; label: string; cls: string }> = [
    { key: 'all',     label: `All (${counts.all})`,         cls: 'bg-slate-100 text-slate-600 hover:bg-slate-200' },
    { key: 'passing', label: `Pass (${counts.passing})`,    cls: 'bg-emerald-50 text-emerald-700 hover:bg-emerald-100' },
    { key: 'failing', label: `Failed (${counts.failing})`,  cls: 'bg-red-50 text-red-700 hover:bg-red-100' },
    { key: 'pending', label: `Pending (${counts.pending})`, cls: 'bg-violet-50 text-violet-700 hover:bg-violet-100' },
  ];

  return (
    <div>
      <div className="text-xs font-medium text-slate-500 mb-3 uppercase tracking-wide">Stories</div>

      {/* Search Input */}
      <input
        type="text"
        value={search}
        onChange={e => setSearch(e.target.value)}
        placeholder="Search stories…"
        className="w-full px-3 py-1.5 text-xs rounded-lg border border-slate-200 bg-white focus:outline-none focus:ring-2 focus:ring-violet-300 mb-3"
      />

      {/* Filter Buttons */}
      <div className="flex flex-wrap items-center gap-2 mb-3">
        {FILTERS.map(f => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors ${f.cls} ${filter === f.key ? 'ring-2 ring-offset-1 ring-current' : ''}`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* List */}
      <div className="space-y-1 max-h-[600px] overflow-y-auto pr-1">
        {filtered.length === 0 ? (
          <div className="text-xs text-slate-400 italic py-4 text-center">No stories match the current filter</div>
        ) : (
          filtered.map(s => <StoryRow key={s.id} s={s} />)
        )}
      </div>
    </div>
  );
}
