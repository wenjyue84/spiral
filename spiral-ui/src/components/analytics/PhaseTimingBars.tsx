interface PhaseTiming {
  phase: string; durationSec: number; label: string;
}

const PHASE_COLORS: Record<string, string> = {
  R: 'bg-blue-500',
  T: 'bg-cyan-500',
  S: 'bg-teal-500',
  M: 'bg-amber-500',
  I: 'bg-orange-500',
  V: 'bg-emerald-500',
  C: 'bg-violet-500',
};

function fmtDuration(sec: number): string {
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  const remSec = sec % 60;
  return remSec > 0 ? `${min}m ${remSec}s` : `${min}m`;
}

export default function PhaseTimingBars({ data }: { data: PhaseTiming[] }) {
  if (data.length === 0) return null;

  const maxDur = Math.max(1, ...data.map(d => d.durationSec));

  return (
    <div>
      <div className="text-xs font-medium text-slate-500 mb-2 uppercase tracking-wide">
        Phase Timings (Last Iteration)
      </div>
      <div className="space-y-2">
        {data.map(t => {
          const pct = Math.max(3, (t.durationSec / maxDur) * 100);
          const color = PHASE_COLORS[t.phase] ?? 'bg-slate-500';
          return (
            <div key={t.phase} className="flex items-center gap-3">
              <span className="text-xs text-slate-500 w-24 shrink-0 truncate" title={t.label}>
                <span className="font-mono font-bold">{t.phase}</span> {t.label}
              </span>
              <div className="flex-1 h-5 bg-slate-100 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${color} flex items-center justify-end pr-2 transition-all`}
                  style={{ width: `${pct}%` }}
                >
                  {pct > 15 && (
                    <span className="text-[10px] text-white font-medium">{fmtDuration(t.durationSec)}</span>
                  )}
                </div>
              </div>
              {pct <= 15 && (
                <span className="text-[10px] text-slate-500 w-12 text-right shrink-0">{fmtDuration(t.durationSec)}</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
