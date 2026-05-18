import { useMemo } from 'react';
import { usePhaseStats } from '../hooks/usePhaseStats';
import type { RawEvent } from '../hooks/usePhaseStats';

interface PhaseStatsCardProps {
  projectName?: string;
  initialEvents?: RawEvent[];
}

/**
 * Phase Stats Grid Component
 *
 * Renders a 2×4 color-coded grid showing per-phase success rates, story counts, and avg durations.
 * Updates in real-time via SSE when new events arrive.
 *
 * Acceptance Criteria:
 * 1. Reads and groups spiral_events by phase (A, R, T, S, E, M, I, V)
 * 2. Renders 2×4 grid with phase name, success %, story count, avg duration
 * 3. Color-codes by success rate threshold: green >90%, yellow 70–90%, red <70%
 * 4. Real-time updates via SSE listener (no manual refresh)
 */
export default function PhaseStatsCard({
  projectName = 'default',
  initialEvents = [],
}: PhaseStatsCardProps) {
  const { stats, isLoading } = usePhaseStats(projectName, initialEvents);

  // Determine color based on success rate
  const getColorClass = (successRate: number): string => {
    if (successRate >= 90) return 'bg-green-50 border-green-200';
    if (successRate >= 70) return 'bg-yellow-50 border-yellow-200';
    return 'bg-red-50 border-red-200';
  };

  // Determine text color for success rate
  const getTextColorClass = (successRate: number): string => {
    if (successRate >= 90) return 'text-green-700';
    if (successRate >= 70) return 'text-yellow-700';
    return 'text-red-700';
  };

  // Get grid layout with stats in order (A-H, 2 rows × 4 cols)
  const gridStats = useMemo(() => {
    const gridLayout = [];
    const phaseOrder = ['A', 'R', 'T', 'S', 'E', 'M', 'I', 'V'];

    for (const phase of phaseOrder) {
      const stat = stats.find(s => s.phase === phase);
      gridLayout.push(stat || {
        phase,
        label: phase,
        successRate: 0,
        successCount: 0,
        totalCount: 0,
        avgDuration: 0,
      });
    }

    return gridLayout;
  }, [stats]);

  if (isLoading && stats.length === 0) {
    return (
      <div className="p-8 text-center text-slate-500">
        <p className="text-sm font-medium">Loading phase statistics...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-900">Phase Success Rates</h2>
          <p className="mt-1 text-sm text-slate-600">
            Per-phase execution metrics (Green: &gt;90%, Yellow: 70–90%, Red: &lt;70%)
          </p>
        </div>
        {gridStats.length > 0 && (
          <div className="text-right">
            <p className="text-sm text-slate-600">Total Events</p>
            <p className="text-2xl font-bold text-slate-900">
              {gridStats.reduce((sum, s) => sum + s.totalCount, 0)}
            </p>
          </div>
        )}
      </div>

      {stats.length === 0 ? (
        <div className="py-12 text-center">
          <p className="text-slate-500">No phase data available yet</p>
        </div>
      ) : (
        <div className="grid grid-cols-4 gap-4">
          {gridStats.map((stat) => (
            <div
              key={stat.phase}
              className={`rounded-lg border p-4 transition-colors ${getColorClass(stat.successRate)}`}
            >
              {/* Phase Label */}
              <div className="mb-3 flex items-baseline justify-between">
                <h3 className="text-lg font-bold text-slate-900">{stat.phase}</h3>
                <p className="text-xs text-slate-600">{stat.label}</p>
              </div>

              {/* Success Rate */}
              <div className="mb-3">
                <p className={`text-2xl font-bold ${getTextColorClass(stat.successRate)}`}>
                  {stat.successRate.toFixed(1)}%
                </p>
                <p className="text-xs text-slate-600">success rate</p>
              </div>

              {/* Divider */}
              <hr className="my-2 border-slate-200" />

              {/* Story Count */}
              <div className="mb-2">
                <p className="text-sm text-slate-700">
                  <span className="font-semibold">{stat.successCount}</span>
                  <span className="text-slate-500"> / {stat.totalCount}</span>
                </p>
                <p className="text-xs text-slate-600">stories passed</p>
              </div>

              {/* Average Duration */}
              <div>
                <p className="text-sm font-semibold text-slate-700">
                  {stat.avgDuration}s avg
                </p>
                <p className="text-xs text-slate-600">duration</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Legend */}
      <div className="mt-6 flex gap-6 border-t border-slate-200 pt-4 text-xs text-slate-600">
        <div className="flex items-center gap-2">
          <div className="h-4 w-4 rounded bg-green-100" />
          <span>Excellent (≥90%)</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="h-4 w-4 rounded bg-yellow-100" />
          <span>Good (70–90%)</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="h-4 w-4 rounded bg-red-100" />
          <span>Needs Work (&lt;70%)</span>
        </div>
      </div>
    </div>
  );
}
