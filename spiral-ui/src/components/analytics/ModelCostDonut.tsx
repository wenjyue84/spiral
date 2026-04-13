import { useMemo } from 'react';

interface ModelPerformance {
  model: string;
  total: number;
  kept: number;
  successRate: number;
  avgDurationSec: number;
  inputTokens?: number;
  outputTokens?: number;
  costUsd?: number;
}

interface Props {
  data: ModelPerformance[];
}

const getModelColor = (model: string): string => {
  const lower = model.toLowerCase();
  if (lower.includes('haiku')) return '#3b82f6'; // blue
  if (lower.includes('sonnet')) return '#8b5cf6'; // violet
  if (lower.includes('opus')) return '#fbbf24'; // amber
  return '#94a3b8'; // slate default
};

const getModelLabel = (model: string): string => {
  const lower = model.toLowerCase();
  if (lower.includes('haiku')) return 'Haiku';
  if (lower.includes('sonnet')) return 'Sonnet';
  if (lower.includes('opus')) return 'Opus';
  return model;
};

export default function ModelCostDonut({ data }: Props) {
  const metrics = useMemo(() => {
    if (!data || data.length === 0) {
      return { segments: [], totalCost: 0 };
    }

    // Calculate cost per model (fallback to total if costUsd not available)
    const segments = data
      .map(m => ({
        model: m.model,
        label: getModelLabel(m.model),
        cost: m.costUsd ?? m.total * 0.01, // Estimate if not provided
        color: getModelColor(m.model),
      }))
      .filter(s => s.cost > 0)
      .sort((a, b) => b.cost - a.cost);

    const totalCost = segments.reduce((sum, s) => sum + s.cost, 0);

    return { segments, totalCost };
  }, [data]);

  if (!metrics.segments || metrics.segments.length === 0) {
    return null;
  }

  const { segments, totalCost } = metrics;

  // Build conic-gradient
  const gradientStops = segments
    .reduce<Array<{ start: number; end: number; color: string; pct: number }>>(
      (acc, segment) => {
        const pct = (segment.cost / totalCost) * 100;
        const start = acc.length > 0 ? acc[acc.length - 1].end : 0;
        const end = start + pct;
        acc.push({ start, end, color: segment.color, pct });
        return acc;
      },
      []
    )
    .map(s => `${s.color} ${s.start}% ${s.end}%`);

  const conicGradient = `conic-gradient(${gradientStops.join(', ')})`;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-xs font-medium text-slate-500 uppercase tracking-wide">Model Cost Split</div>
        <div className="text-[11px] text-slate-600">Total: ${totalCost.toFixed(2)}</div>
      </div>

      <div className="flex flex-col lg:flex-row gap-6 items-center">
        {/* Donut Chart */}
        <div className="flex items-center justify-center">
          <div className="relative w-48 h-48">
            {/* Outer donut ring */}
            <div
              className="absolute inset-0 rounded-full"
              style={{ background: conicGradient }}
            />
            {/* Inner white circle to create donut hole */}
            <div className="absolute inset-8 bg-white rounded-full" />
            {/* Center text */}
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-center">
                <div className="text-xs text-slate-500 uppercase tracking-wide">Total Cost</div>
                <div className="text-xl font-bold text-slate-700">${totalCost.toFixed(2)}</div>
              </div>
            </div>
          </div>
        </div>

        {/* Legend */}
        <div className="space-y-2 flex-1">
          {segments.map(segment => {
            const pct = ((segment.cost / totalCost) * 100).toFixed(1);
            return (
              <div key={segment.model} className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded-full" style={{ backgroundColor: segment.color }} />
                  <span className="text-slate-700 font-medium">{segment.label}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-slate-600">${segment.cost.toFixed(2)}</span>
                  <span className="text-slate-500 w-10 text-right">{pct}%</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
