interface AgentTelemetryEntry {
  ts: string; workerId: string; storyId: string;
  fromPhase: string; toPhase: string;
  durationMs: number; qualityScore: number; retryCount: number;
}

const PHASE_COLORS: Record<string, string> = {
  R: 'bg-blue-100 text-blue-700',
  T: 'bg-cyan-100 text-cyan-700',
  S: 'bg-teal-100 text-teal-700',
  M: 'bg-amber-100 text-amber-700',
  I: 'bg-orange-100 text-orange-700',
  V: 'bg-emerald-100 text-emerald-700',
  C: 'bg-violet-100 text-violet-700',
  F: 'bg-red-100 text-red-700',
};

function PhaseBadge({ phase }: { phase: string }) {
  const cls = PHASE_COLORS[phase] ?? 'bg-slate-100 text-slate-600';
  return <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-mono font-bold ${cls}`}>{phase}</span>;
}

function fmtDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const sec = ms / 1000;
  if (sec < 60) return `${sec.toFixed(1)}s`;
  const min = Math.floor(sec / 60);
  const remSec = Math.round(sec % 60);
  return `${min}m ${remSec}s`;
}

function fmtTime(ts: string): string {
  if (!ts) return '';
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch { return ts; }
}

export default function AgentTelemetryTable({ data }: { data: AgentTelemetryEntry[] }) {
  if (data.length === 0) return null;

  return (
    <div>
      <div className="text-xs font-medium text-slate-500 mb-2 uppercase tracking-wide">
        Agent Phase Telemetry ({data.length} transitions)
      </div>
      <div className="rounded-lg border border-slate-200 overflow-hidden max-h-[400px] overflow-y-auto">
        <table className="w-full text-xs">
          <thead className="bg-slate-50 text-slate-500 sticky top-0">
            <tr>
              <th className="text-left px-3 py-2">Time</th>
              <th className="text-center px-3 py-2">Worker</th>
              <th className="text-left px-3 py-2">Story</th>
              <th className="text-center px-3 py-2">Transition</th>
              <th className="text-right px-3 py-2">Duration</th>
              <th className="text-right px-3 py-2">Quality</th>
              <th className="text-right px-3 py-2">Retries</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {data.map((entry, i) => (
              <tr key={i} className="hover:bg-slate-50">
                <td className="px-3 py-1.5 text-slate-500 font-mono">{fmtTime(entry.ts)}</td>
                <td className="px-3 py-1.5 text-center">
                  <span className="inline-block px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 text-[10px] font-mono">
                    W{entry.workerId}
                  </span>
                </td>
                <td className="px-3 py-1.5 font-mono text-slate-700">{entry.storyId}</td>
                <td className="px-3 py-1.5 text-center whitespace-nowrap">
                  <PhaseBadge phase={entry.fromPhase} />
                  <span className="mx-1 text-slate-400">&rarr;</span>
                  <PhaseBadge phase={entry.toPhase} />
                </td>
                <td className="px-3 py-1.5 text-right text-slate-600">{fmtDuration(entry.durationMs)}</td>
                <td className="px-3 py-1.5 text-right">
                  <span className={entry.qualityScore >= 7 ? 'text-emerald-600' : entry.qualityScore >= 4 ? 'text-amber-600' : 'text-red-600'}>
                    {entry.qualityScore > 0 ? entry.qualityScore.toFixed(1) : '-'}
                  </span>
                </td>
                <td className="px-3 py-1.5 text-right">
                  <span className={entry.retryCount >= 3 ? 'text-red-600 font-bold' : 'text-slate-500'}>
                    {entry.retryCount}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
