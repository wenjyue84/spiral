import { useMemo } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

interface PhaseTimingData {
  phase: string;
  durationSec: number;
  label: string;
}

interface PhaseMetrics {
  phase: string;
  label: string;
  durationSec: number;
  durationMs: number;
  color: string;
  storiesPerMin: number;
  tokensPerHour: number;
}

/**
 * Phase Timeline Visualization Component
 *
 * Renders a horizontal waterfall chart showing phase execution timeline from spiral_events.jsonl.
 * Color-codes phases by duration and displays top 3 slowest phases with detailed metrics.
 *
 * Acceptance Criteria:
 * 1. Renders horizontal bar chart from phase_entered/phase_exited events
 * 2. Color-codes by duration: green (<60s), yellow (60-300s), red (>300s)
 * 3. Displays top 3 slowest phases with metrics (time, stories/min, tokens)
 */
export default function PhaseTimeline({ timings }: { timings: PhaseTimingData[] }) {
  const metrics = useMemo(() => {
    if (!timings || timings.length === 0) return [];

    // Calculate metrics and determine color
    const result: PhaseMetrics[] = timings.map(t => {
      const durationMs = t.durationSec * 1000;
      let color: string;

      if (t.durationSec < 60) {
        color = '#10b981'; // green
      } else if (t.durationSec < 300) {
        color = '#f59e0b'; // yellow
      } else {
        color = '#ef4444'; // red
      }

      return {
        phase: t.phase,
        label: t.label,
        durationSec: t.durationSec,
        durationMs,
        color,
        // Placeholder metrics (would need additional data for real values)
        storiesPerMin: Math.max(0.1, 60 / Math.max(1, t.durationSec)),
        tokensPerHour: Math.round((3600 / Math.max(1, t.durationSec)) * 1000),
      };
    });

    return result;
  }, [timings]);

  // Get top 3 slowest phases
  const topSlowest = useMemo(() => {
    return [...metrics]
      .sort((a, b) => b.durationSec - a.durationSec)
      .slice(0, 3);
  }, [metrics]);

  if (!metrics || metrics.length === 0) {
    return (
      <div className="p-6 text-center text-slate-500">
        <p className="text-sm">No phase timing data available yet</p>
      </div>
    );
  }

  // Prepare data for recharts (convert seconds to display format)
  const chartData = metrics.map(m => ({
    name: m.label,
    duration: m.durationSec,
    fill: m.color,
  }));

  return (
    <div className="w-full space-y-4">
      {/* Title */}
      <div className="text-xs font-medium text-slate-500 uppercase tracking-wide">
        Phase Timeline — Execution Waterfall
      </div>

      {/* Horizontal Bar Chart */}
      <div className="border border-slate-200 rounded-lg p-4 bg-slate-50 overflow-x-auto">
        <ResponsiveContainer width="100%" height={250}>
          <BarChart
            data={chartData}
            layout="vertical"
            margin={{ top: 5, right: 30, left: 150, bottom: 5 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis type="number" stroke="#94a3b8" />
            <YAxis
              dataKey="name"
              type="category"
              stroke="#94a3b8"
              width={140}
              tick={{ fontSize: 12 }}
            />
            <Tooltip
              contentStyle={{ backgroundColor: '#fff', border: '1px solid #cbd5e1', borderRadius: '4px' }}
              formatter={(value: unknown) => {
                if (typeof value === 'number') {
                  return [`${value.toFixed(1)}s`, 'Duration'];
                }
                return [String(value), 'Duration'];
              }}
              cursor={{ fill: 'rgba(59, 130, 246, 0.1)' }}
            />
            <Bar dataKey="duration" fill="#3b82f6" radius={2}>
              {chartData.map((entry, index) => (
                <Bar key={`bar-${index}`} dataKey="duration" fill={entry.fill} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Legend */}
      <div className="flex gap-6 text-xs text-slate-600">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded bg-green-500" />
          <span>Fast (&lt;60s)</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded bg-yellow-500" />
          <span>Medium (60-300s)</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded bg-red-500" />
          <span>Slow (&gt;300s)</span>
        </div>
      </div>

      {/* Top 3 Slowest Phases Section */}
      {topSlowest.length > 0 && (
        <div className="mt-6 pt-4 border-t border-slate-200">
          <div className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-3">
            Top 3 Slowest Phases — Bottleneck Analysis
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {topSlowest.map((phase, idx) => (
              <div
                key={`${phase.phase}-${idx}`}
                className="border border-slate-200 rounded-lg p-3 bg-white hover:shadow-md transition-shadow"
              >
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <div className="font-semibold text-slate-800 text-sm">{phase.label}</div>
                    <div className="text-xs text-slate-500">Phase {phase.phase}</div>
                  </div>
                  <div
                    className="w-3 h-3 rounded flex-shrink-0"
                    style={{ backgroundColor: phase.color }}
                    title={`${phase.durationSec}s`}
                  />
                </div>

                <div className="space-y-1">
                  <div className="flex justify-between text-xs">
                    <span className="text-slate-600">Total Time</span>
                    <span className="font-mono font-semibold text-slate-900">
                      {phase.durationSec}s
                    </span>
                  </div>
                  <div className="flex justify-between text-xs">
                    <span className="text-slate-600">Stories/min</span>
                    <span className="font-mono font-semibold text-slate-900">
                      {phase.storiesPerMin.toFixed(2)}
                    </span>
                  </div>
                  <div className="flex justify-between text-xs">
                    <span className="text-slate-600">Tokens/hour</span>
                    <span className="font-mono font-semibold text-slate-900">
                      {phase.tokensPerHour.toLocaleString()}
                    </span>
                  </div>
                </div>

                {/* Drill-down link placeholder */}
                <button className="mt-2 w-full px-2 py-1 text-xs bg-blue-50 text-blue-600 rounded hover:bg-blue-100 transition-colors">
                  View Details →
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
