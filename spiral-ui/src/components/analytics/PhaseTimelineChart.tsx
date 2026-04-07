import { usePhaseTimings, PhaseTimingData } from '../hooks/usePhaseTimings';

interface PhaseTimelineChartProps {
  timings: PhaseTimingData[];
}

/**
 * Phase Duration Timeline Chart
 * Displays a bar chart of all 12 SPIRAL phases with durations
 * Highlights the slowest phase in red for bottleneck identification
 */
export default function PhaseTimelineChart({ timings }: PhaseTimelineChartProps) {
  const processedTimings = usePhaseTimings(timings);

  if (!processedTimings || processedTimings.length === 0) {
    return (
      <div className="p-6 text-center text-slate-500">
        <p className="text-sm">No phase timing data available yet</p>
      </div>
    );
  }

  // Find max duration for scaling
  const maxMs = Math.max(...processedTimings.map(t => t.durationMs), 1);
  const chartHeight = 300;
  const barWidth = 60;
  const gap = 8;
  const padding = 40;
  const chartWidth = processedTimings.length * (barWidth + gap) + padding * 2;

  return (
    <div className="w-full">
      <div className="text-xs font-medium text-slate-500 mb-4 uppercase tracking-wide">
        Phase Duration Timeline (Last Iteration)
      </div>

      <div className="overflow-x-auto border border-slate-200 rounded-lg p-4 bg-slate-50">
        <svg width={chartWidth} height={chartHeight + 80} className="min-w-full">
          {/* Y-axis */}
          <line
            x1={padding}
            y1={10}
            x2={padding}
            y2={chartHeight}
            stroke="#e2e8f0"
            strokeWidth="2"
          />

          {/* X-axis */}
          <line
            x1={padding}
            y1={chartHeight}
            x2={chartWidth - padding}
            y2={chartHeight}
            stroke="#e2e8f0"
            strokeWidth="2"
          />

          {/* Y-axis labels (milliseconds) */}
          {[0, 0.25, 0.5, 0.75, 1].map((ratio, i) => {
            const y = chartHeight - ratio * (chartHeight - 30);
            const ms = Math.round(ratio * maxMs);
            return (
              <g key={`y-label-${i}`}>
                <line x1={padding - 4} y1={y} x2={padding} y2={y} stroke="#cbd5e1" strokeWidth="1" />
                <text
                  x={padding - 8}
                  y={y + 4}
                  textAnchor="end"
                  fontSize="11"
                  fill="#64748b"
                  className="font-mono"
                >
                  {ms}ms
                </text>
              </g>
            );
          })}

          {/* Bars */}
          {processedTimings.map((timing, idx) => {
            const x = padding + idx * (barWidth + gap);
            const heightRatio = maxMs > 0 ? timing.durationMs / maxMs : 0;
            const barHeight = heightRatio * (chartHeight - 30);
            const barY = chartHeight - barHeight;
            const barColor = timing.isBottleneck ? '#ef4444' : '#94a3b8';

            return (
              <g key={timing.phase}>
                {/* Bar */}
                <rect
                  x={x}
                  y={barY}
                  width={barWidth}
                  height={barHeight}
                  fill={barColor}
                  rx="2"
                  className="hover:opacity-80 transition-opacity cursor-pointer"
                >
                  <title>{timing.label}: {timing.durationMs}ms</title>
                </rect>

                {/* Duration label (inside or above bar) */}
                {barHeight > 25 ? (
                  <text
                    x={x + barWidth / 2}
                    y={barY + barHeight / 2}
                    textAnchor="middle"
                    dominantBaseline="middle"
                    fontSize="11"
                    fontWeight="bold"
                    fill="white"
                    className="pointer-events-none"
                  >
                    {timing.durationMs}ms
                  </text>
                ) : (
                  <text
                    x={x + barWidth / 2}
                    y={barY - 5}
                    textAnchor="middle"
                    fontSize="10"
                    fill={barColor}
                    fontWeight="bold"
                    className="pointer-events-none"
                  >
                    {timing.durationMs}ms
                  </text>
                )}

                {/* Phase label */}
                <text
                  x={x + barWidth / 2}
                  y={chartHeight + 18}
                  textAnchor="middle"
                  fontSize="12"
                  fontWeight="bold"
                  fill="#1e293b"
                >
                  {timing.phase}
                </text>

                {/* Phase name tooltip */}
                <text
                  x={x + barWidth / 2}
                  y={chartHeight + 35}
                  textAnchor="middle"
                  fontSize="10"
                  fill="#64748b"
                  className="pointer-events-none"
                >
                  {timing.label.split(' ').slice(0, 1).join(' ')}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      {/* Legend */}
      <div className="mt-4 flex gap-6 text-xs text-slate-600">
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 rounded bg-slate-400" />
          <span>Normal Phase</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 rounded bg-red-500" />
          <span>Bottleneck (Slowest)</span>
        </div>
      </div>
    </div>
  );
}
