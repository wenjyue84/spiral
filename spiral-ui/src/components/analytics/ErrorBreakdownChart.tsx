import { useState, useEffect } from 'react';

// ── Types ─────────────────────────────────────────────────────────────────────

interface ErrorBreakdownData {
  phases: Record<string, Record<string, number>>;
  story_ids?: Record<string, Record<string, string[]>>;
  total_errors: number;
  iterations_filter: { mode: string; n?: number; iteration?: number };
}

const CATEGORY_COLORS: Record<string, { bg: string; text: string; label: string }> = {
  timeout:          { bg: 'bg-amber-400',  text: 'text-amber-700',  label: 'Timeout' },
  oom:              { bg: 'bg-red-500',    text: 'text-red-700',    label: 'OOM' },
  model_error:      { bg: 'bg-violet-500', text: 'text-violet-700', label: 'Model Error' },
  validation_error: { bg: 'bg-orange-400', text: 'text-orange-700', label: 'Validation' },
  file_conflict:    { bg: 'bg-rose-400',   text: 'text-rose-700',   label: 'File Conflict' },
};
const DEFAULT_COLOR = { bg: 'bg-slate-400', text: 'text-slate-600', label: '' };

const PHASE_ORDER = ['A', 'R', 'T', 'S', 'E', 'M', 'X', 'I', 'V', 'C', 'L'];

// ── Component ─────────────────────────────────────────────────────────────────

export default function ErrorBreakdownChart() {
  const [data, setData] = useState<ErrorBreakdownData | null>(null);
  const [loading, setLoading] = useState(true);
  const [iterations, setIterations] = useState(5);
  const [selectedPhase, setSelectedPhase] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    fetch(`/api/dashboard/error-breakdown?iterations=${iterations}`)
      .then(r => r.json())
      .then((d: ErrorBreakdownData) => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [iterations]);

  if (loading) return (
    <div className="text-xs text-slate-400 py-2">Loading error breakdown…</div>
  );
  if (!data || data.total_errors === 0) return (
    <div className="text-xs text-slate-400 py-2 italic">No errors recorded in last {iterations} iterations.</div>
  );

  const { phases } = data;

  // Sort phases: known phases in order, then unknown alphabetically
  const sortedPhases = [
    ...PHASE_ORDER.filter(p => p in phases),
    ...Object.keys(phases).filter(p => !PHASE_ORDER.includes(p)).sort(),
  ];

  // Max total errors in any phase (for bar height scaling)
  const maxPhaseErrors = Math.max(1, ...sortedPhases.map(p =>
    Object.values(phases[p]).reduce((a, b) => a + b, 0)
  ));

  // All unique categories across all phases
  const allCategories = [...new Set(
    sortedPhases.flatMap(p => Object.keys(phases[p]))
  )];

  return (
    <div id="errors">
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs font-medium text-slate-500 uppercase tracking-wide">
          Error Breakdown by Phase
          <span className="ml-2 text-slate-400 normal-case font-normal">
            ({data.total_errors} total errors)
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-slate-400">Last</span>
          {[3, 5, 10].map(n => (
            <button
              key={n}
              onClick={() => setIterations(n)}
              className={`text-[10px] px-2 py-0.5 rounded ${
                iterations === n
                  ? 'bg-violet-600 text-white'
                  : 'bg-slate-100 text-slate-500 hover:bg-slate-200'
              }`}
            >
              {n}
            </button>
          ))}
          <span className="text-[10px] text-slate-400">iterations</span>
        </div>
      </div>

      {/* Stacked bar chart */}
      <div className="flex items-end gap-3 h-32 border-b border-l border-slate-200 px-2 pb-1 mb-3">
        {sortedPhases.map(phase => {
          const cats = phases[phase];
          const total = Object.values(cats).reduce((a, b) => a + b, 0);
          const heightPct = Math.max(8, (total / maxPhaseErrors) * 100);
          return (
            <div
              key={phase}
              className="flex flex-col items-center flex-1 min-w-0 cursor-pointer group"
              onClick={() => setSelectedPhase(selectedPhase === phase ? null : phase)}
              title={`Phase ${phase}: ${total} error${total !== 1 ? 's' : ''} — click to drill down`}
            >
              <div className="text-[9px] text-slate-500 mb-0.5 group-hover:text-slate-700">{total}</div>
              <div
                className={`w-full max-w-[36px] rounded-t overflow-hidden flex flex-col-reverse transition-all ${
                  selectedPhase === phase ? 'ring-2 ring-violet-400' : ''
                }`}
                style={{ height: `${heightPct}%` }}
              >
                {Object.entries(cats).map(([cat, count]) => {
                  const colors = CATEGORY_COLORS[cat] ?? DEFAULT_COLOR;
                  const pct = (count / total) * 100;
                  return (
                    <div
                      key={cat}
                      className={`w-full ${colors.bg} transition-all`}
                      style={{ height: `${pct}%`, minHeight: count > 0 ? '4px' : 0 }}
                      title={`${cat}: ${count}`}
                    />
                  );
                })}
              </div>
              <div className={`text-[9px] mt-0.5 font-mono font-bold ${
                selectedPhase === phase ? 'text-violet-600' : 'text-slate-500'
              }`}>
                {phase}
              </div>
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div className="flex gap-3 flex-wrap mb-3">
        {allCategories.map(cat => {
          const colors = CATEGORY_COLORS[cat] ?? DEFAULT_COLOR;
          return (
            <span key={cat} className="flex items-center gap-1 text-[10px] text-slate-500">
              <span className={`w-2 h-2 rounded-sm inline-block ${colors.bg}`} />
              {colors.label || cat}
            </span>
          );
        })}
      </div>

      {/* Drill-down table */}
      {selectedPhase && phases[selectedPhase] && (
        <div className="rounded-lg border border-violet-200 bg-violet-50 overflow-hidden">
          <div className="px-3 py-2 text-xs font-semibold text-violet-700 border-b border-violet-200 flex items-center justify-between">
            <span>Phase {selectedPhase} — Error Categories</span>
            <button
              onClick={() => setSelectedPhase(null)}
              className="text-violet-400 hover:text-violet-700 text-[10px]"
            >
              close ×
            </button>
          </div>
          <div className="p-3 space-y-1.5">
            {Object.entries(phases[selectedPhase])
              .sort(([, a], [, b]) => b - a)
              .map(([cat, count]) => {
                const colors = CATEGORY_COLORS[cat] ?? DEFAULT_COLOR;
                const total = Object.values(phases[selectedPhase]).reduce((a, b) => a + b, 0);
                const pct = Math.round((count / total) * 100);
                const catStoryIds = data?.story_ids?.[selectedPhase]?.[cat] ?? [];
                return (
                  <div key={cat}>
                    <div className="flex items-center gap-2">
                      <span className={`text-[10px] w-28 shrink-0 ${colors.text}`}>
                        {colors.label || cat}
                      </span>
                      <div className="flex-1 h-3 bg-white/60 rounded-full overflow-hidden border border-violet-100">
                        <div
                          className={`h-full rounded-full ${colors.bg}`}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <span className="text-[10px] text-slate-600 w-12 text-right shrink-0">
                        {count} ({pct}%)
                      </span>
                    </div>
                    {catStoryIds.length > 0 && (
                      <div className="ml-28 pl-2 mt-0.5 flex gap-1 flex-wrap">
                        {catStoryIds.map(sid => (
                          <span key={sid} className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-white border border-violet-100 text-violet-600">
                            {sid}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
          </div>
        </div>
      )}
    </div>
  );
}
