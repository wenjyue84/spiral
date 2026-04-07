import { useMemo } from 'react';

export interface PhaseTimingData {
  phase: string;
  durationSec: number;
  label: string;
}

export interface ProcessedPhaseiming {
  phase: string;
  durationMs: number;
  label: string;
  isBottleneck: boolean;
}

/**
 * Hook to process and enhance phase timing data for visualization
 * Converts seconds to milliseconds, identifies the slowest phase
 */
export function usePhaseTimings(timings: PhaseTimingData[]): ProcessedPhaseiming[] {
  return useMemo(() => {
    if (!timings || timings.length === 0) return [];

    // Find maximum duration to identify bottleneck
    const maxDuration = Math.max(...timings.map(t => t.durationSec), 0);

    // Convert to milliseconds and mark bottleneck
    return timings.map(timing => ({
      phase: timing.phase,
      durationMs: Math.round(timing.durationSec * 1000),
      label: timing.label,
      isBottleneck: timing.durationSec === maxDuration && maxDuration > 0,
    }));
  }, [timings]);
}
