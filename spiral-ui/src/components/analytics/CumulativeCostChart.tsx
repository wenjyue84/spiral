import { useMemo } from 'react';

interface TrendPoint {
  iter: number;
  cumulativeCost: number;
  cumulativePassed: number;
}

interface Props {
  data: TrendPoint[];
}

export default function CumulativeCostChart({ data }: Props) {
  const metrics = useMemo(() => {
    if (!data || data.length === 0) {
      return { minIter: 0, maxIter: 0, maxCost: 0, maxPassed: 0, width: 0, height: 0 };
    }

    const minIter = Math.min(...data.map(d => d.iter));
    const maxIter = Math.max(...data.map(d => d.iter));
    const maxCost = Math.max(...data.map(d => d.cumulativeCost));
    const maxPassed = Math.max(...data.map(d => d.cumulativePassed)) || 1;

    return { minIter, maxIter, maxCost, maxPassed, width: 600, height: 300 };
  }, [data]);

  if (!data || data.length === 0) {
    return (
      <div className="p-4 text-sm text-slate-500">
        No cumulative data available yet
      </div>
    );
  }

  const { minIter, maxIter, maxCost, maxPassed, width, height } = metrics;
  const padding = 60;
  const graphWidth = width - 2 * padding;
  const graphHeight = height - 2 * padding;

  // Calculate scales
  const xScale = (iter: number) => padding + ((iter - minIter) / (maxIter - minIter || 1)) * graphWidth;
  const yLeftScale = (cost: number) => height - padding - (cost / (maxCost || 1)) * graphHeight;
  const yRightScale = (passed: number) => height - padding - (passed / (maxPassed || 1)) * graphHeight;

  // Build SVG paths
  const costPath = `M ${data
    .map((d, i) => `${xScale(d.iter)},${yLeftScale(d.cumulativeCost)}`)
    .join(' L ')}`;

  const passedPath = `M ${data
    .map((d, i) => `${xScale(d.iter)},${yRightScale(d.cumulativePassed)}`)
    .join(' L ')}`;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="text-xs font-medium text-slate-500 uppercase tracking-wide">Cumulative Cost & Stories Passed</div>
        <div className="flex items-center gap-4 text-[11px]">
          <div className="flex items-center gap-1">
            <div className="w-3 h-0.5 bg-emerald-500" />
            <span className="text-slate-600">Cumulative Cost ($)</span>
          </div>
          <div className="flex items-center gap-1">
            <div className="w-3 h-0.5 bg-violet-500" />
            <span className="text-slate-600">Cumulative Passed</span>
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-3 overflow-x-auto">
        <svg width={width} height={height} className="min-w-max">
          {/* Grid lines (optional, light) */}
          {Array.from({ length: 5 }).map((_, i) => {
            const y = padding + (i / 4) * graphHeight;
            return (
              <line key={`grid-${i}`} x1={padding} y1={y} x2={width - padding} y2={y} stroke="#f1f5f9" strokeWidth={1} />
            );
          })}

          {/* Axes */}
          <line x1={padding} y1={padding} x2={padding} y2={height - padding} stroke="#cbd5e1" strokeWidth={2} />
          <line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} stroke="#cbd5e1" strokeWidth={2} />
          <line x1={width - padding} y1={padding} x2={width - padding} y2={height - padding} stroke="#cbd5e1" strokeWidth={2} />

          {/* Cost line (left y-axis) */}
          <path d={costPath} fill="none" stroke="#10b981" strokeWidth={2} />

          {/* Passed line (right y-axis) */}
          <path d={passedPath} fill="none" stroke="#8b5cf6" strokeWidth={2} />

          {/* Data points */}
          {data.map((d) => (
            <g key={d.iter}>
              <circle cx={xScale(d.iter)} cy={yLeftScale(d.cumulativeCost)} r={4} fill="#10b981" opacity={0.8} />
              <circle cx={xScale(d.iter)} cy={yRightScale(d.cumulativePassed)} r={4} fill="#8b5cf6" opacity={0.8} />
            </g>
          ))}

          {/* X-axis labels (iterations) */}
          {data.map((d, i) => (
            i % Math.max(1, Math.floor(data.length / 5)) === 0 && (
              <g key={`x-label-${d.iter}`}>
                <text x={xScale(d.iter)} y={height - padding + 20} textAnchor="middle" className="text-[11px] fill-slate-500">
                  i{d.iter}
                </text>
              </g>
            )
          ))}

          {/* Left Y-axis label */}
          <text x={20} y={30} className="text-[11px] fill-slate-600 font-medium">
            $ (cost)
          </text>

          {/* Right Y-axis label */}
          <text x={width - 40} y={30} className="text-[11px] fill-slate-600 font-medium">
            passed
          </text>

          {/* Y-axis tick labels (left) */}
          {Array.from({ length: 5 }).map((_, i) => {
            const cost = (i / 4) * maxCost;
            const y = height - padding - (i / 4) * graphHeight;
            return (
              <text key={`y-left-${i}`} x={padding - 8} y={y + 4} textAnchor="end" className="text-[10px] fill-slate-500">
                ${cost.toFixed(0)}
              </text>
            );
          })}

          {/* Y-axis tick labels (right) */}
          {Array.from({ length: 5 }).map((_, i) => {
            const passed = Math.round((i / 4) * maxPassed);
            const y = height - padding - (i / 4) * graphHeight;
            return (
              <text key={`y-right-${i}`} x={width - padding + 8} y={y + 4} textAnchor="start" className="text-[10px] fill-slate-500">
                {passed}
              </text>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
