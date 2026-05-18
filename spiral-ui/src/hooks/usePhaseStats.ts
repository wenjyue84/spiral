import { useMemo, useState, useCallback } from 'react';
import { useSSE } from './useSSE';
import type { SSEEvent } from './useSSE';

export interface PhaseStats {
  phase: string;
  label: string;
  successRate: number;
  successCount: number;
  totalCount: number;
  avgDuration: number;
}

export interface RawEvent {
  phase?: string;
  event_type?: string;
  type?: string;
  duration?: number;
  story_id?: string;
  status?: string;
  [key: string]: unknown;
}

/**
 * Parse raw events into structured phase statistics
 * Groups events by phase, counts successes, and calculates averages
 */
export function parseEventLog(events: RawEvent[]): Map<string, RawEvent[]> {
  const grouped = new Map<string, RawEvent[]>();

  for (const event of events) {
    const phase = event.phase as string;
    if (!phase) continue;

    if (!grouped.has(phase)) {
      grouped.set(phase, []);
    }
    grouped.get(phase)!.push(event);
  }

  return grouped;
}

/**
 * Compute phase statistics from grouped events
 * Returns success rate, counts, and average duration per phase
 */
export function computePhaseStats(groupedEvents: Map<string, RawEvent[]>): PhaseStats[] {
  const PHASE_LABELS: Record<string, string> = {
    A: 'AI Suggest',
    R: 'Research',
    T: 'Test Synth',
    S: 'Story Valid',
    E: 'Enrichment',
    M: 'Merge',
    I: 'Implement',
    V: 'Validate',
  };

  const phases = ['A', 'R', 'T', 'S', 'E', 'M', 'I', 'V'];
  const stats: PhaseStats[] = [];

  for (const phase of phases) {
    const events = groupedEvents.get(phase) || [];

    if (events.length === 0) {
      stats.push({
        phase,
        label: PHASE_LABELS[phase] || phase,
        successRate: 0,
        successCount: 0,
        totalCount: 0,
        avgDuration: 0,
      });
      continue;
    }

    // Count successes: events with status === 'success' or event_type === 'phase_exited'
    const successCount = events.filter(
      e => (e.status as string) === 'success' || (e.event_type as string) === 'phase_exited',
    ).length;

    // Calculate average duration (in seconds)
    const durations = events
      .map(e => e.duration as number)
      .filter((d): d is number => typeof d === 'number' && d > 0);
    const avgDuration = durations.length > 0 ? durations.reduce((a, b) => a + b, 0) / durations.length : 0;

    const successRate = events.length > 0 ? (successCount / events.length) * 100 : 0;

    stats.push({
      phase,
      label: PHASE_LABELS[phase] || phase,
      successRate,
      successCount,
      totalCount: events.length,
      avgDuration: Math.round(avgDuration),
    });
  }

  return stats;
}

/**
 * Hook to fetch and track phase statistics with real-time updates
 * Listens to SSE events and updates stats as new events arrive
 */
export function usePhaseStats(
  projectName: string | undefined,
  initialEvents: RawEvent[] = [],
) {
  const [events, setEvents] = useState<RawEvent[]>(initialEvents);

  // Listen for SSE events
  const handleNewEvent = useCallback((sseEvent: SSEEvent) => {
    const rawEvent: RawEvent = {
      phase: sseEvent.phase,
      event_type: sseEvent.event_type || sseEvent.type,
      duration: sseEvent.duration as number | undefined,
      story_id: sseEvent.story_id as string | undefined,
      status: sseEvent.status as string | undefined,
      ...sseEvent,
    };

    // Only add events with a phase field
    if (rawEvent.phase) {
      setEvents(prev => [...prev, rawEvent]);
    }
  }, []);

  useSSE(projectName, handleNewEvent);

  // Compute stats from events
  const stats = useMemo(() => {
    if (events.length === 0) return [];
    const grouped = parseEventLog(events);
    return computePhaseStats(grouped);
  }, [events]);

  return {
    stats,
    isLoading: false,
    eventCount: events.length,
  };
}
