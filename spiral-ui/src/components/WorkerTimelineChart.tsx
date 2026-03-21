import { useState, useEffect } from 'react';

interface PhaseBlock {
  phase: string;
  status: 'running' | 'completed' | 'failed';
  started_at: string;
  ended_at?: string;
  tokens?: number;
  model?: string;
}

interface WorkerQueue {
  worker_id: string;
  phases?: PhaseBlock[];
}

type WorkerData = Record<string, WorkerQueue>;

const WORKERS = ['worker-1', 'worker-2', 'worker-3'];

function blockColor(status: string): string {
  if (status === 'running') return '#3b82f6';
  if (status === 'failed') return '#ef4444';
  return '#22c55e';
}

function durSec(start: string, end?: string): number {
  return Math.max(1, Math.round(((end ? new Date(end).getTime() : Date.now()) - new Date(start).getTime()) / 1000));
}

function tooltipText(b: PhaseBlock): string {
  const parts = [`Phase: ${b.phase}`, `Duration: ${durSec(b.started_at, b.ended_at)}s`, `Status: ${b.status}`];
  if (b.tokens) parts.push(`Tokens: ${b.tokens}`);
  if (b.model) parts.push(`Model: ${b.model}`);
  return parts.join('\n');
}

export default function WorkerTimelineChart() {
  const [data, setData] = useState<WorkerData>({});
  const [err, setErr] = useState('');

  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const settled = await Promise.allSettled(
          WORKERS.map(w => fetch(`/api/workers/${w}/queue`).then(r => r.ok ? (r.json() as Promise<WorkerQueue>) : Promise.reject()))
        );
        if (!active) return;
        const next: WorkerData = {};
        settled.forEach((r, i) => { if (r.status === 'fulfilled') next[WORKERS[i]] = r.value; });
        setData(next);
        setErr('');
      } catch {
        if (active) setErr('Failed to load worker data');
      }
    };
    poll();
    const id = setInterval(poll, 1000);
    return () => { active = false; clearInterval(id); };
  }, []);

  const allBlocks = Object.values(data).flatMap(w => w.phases ?? []);
  const minTs = allBlocks.length ? Math.min(...allBlocks.map(b => new Date(b.started_at).getTime())) : Date.now() - 60000;
  const maxTs = allBlocks.length ? Math.max(...allBlocks.map(b => b.ended_at ? new Date(b.ended_at).getTime() : Date.now())) : Date.now();
  const span = Math.max(1, maxTs - minTs);

  return (
    <div>
      <div className="text-xs font-medium text-slate-500 mb-2 uppercase tracking-wide">
        Worker Phase Timeline
      </div>
      {err && <div className="text-xs text-red-500 mb-2">{err}</div>}
      {!Object.keys(data).length && !err && (
        <div className="text-xs text-slate-400 italic">No worker data available</div>
      )}
      {WORKERS.map(wid => {
        const phases = data[wid]?.phases ?? [];
        return (
          <div key={wid} className="mb-3">
            <div className="text-[11px] font-mono text-slate-500 mb-1">{wid}</div>
            <div className="relative h-7 bg-slate-100 rounded overflow-hidden">
              {phases.length === 0 && (
                <div className="absolute inset-0 flex items-center justify-center text-[10px] text-slate-400">idle</div>
              )}
              {phases.map((b, i) => {
                const left = ((new Date(b.started_at).getTime() - minTs) / span) * 100;
                const endMs = b.ended_at ? new Date(b.ended_at).getTime() : Date.now();
                const width = ((endMs - new Date(b.started_at).getTime()) / span) * 100;
                return (
                  <div
                    key={i}
                    className="absolute top-0 bottom-0 flex items-center justify-center text-[10px] text-white font-mono cursor-default"
                    style={{ left: `${left}%`, width: `${Math.max(2, width)}%`, backgroundColor: blockColor(b.status) }}
                    title={tooltipText(b)}
                  >
                    {width > 8 ? b.phase : ''}
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
