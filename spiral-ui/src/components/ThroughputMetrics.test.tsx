import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import ThroughputMetrics from './ThroughputMetrics';

global.fetch = vi.fn();

const mockThroughputData = {
  velocity: 12.5,
  cycleTimeByComplexity: [
    { complexity: 'small', medianCycleTimeMinutes: 15 },
    { complexity: 'medium', medianCycleTimeMinutes: 45 },
    { complexity: 'large', medianCycleTimeMinutes: 120 },
  ],
};

describe('ThroughputMetrics', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders ThroughputMetrics showing X stories/hour and cycle time by complexity band', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => mockThroughputData,
    });

    render(<ThroughputMetrics isRunning={true} />);

    await waitFor(() => {
      expect(screen.getByText(/12.5/)).toBeInTheDocument();
    });

    expect(screen.getByText(/stories\/hour/)).toBeInTheDocument();
    expect(screen.getByText(/Median Cycle Time by Complexity/)).toBeInTheDocument();
    // Verify the recharts container is rendered (which contains the chart data)
    const chartContainers = document.querySelectorAll('.recharts-responsive-container');
    expect(chartContainers.length).toBeGreaterThan(0);
  });

  it('fetches from /api/throughput on mount when iteration is running', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => mockThroughputData,
    });

    render(<ThroughputMetrics isRunning={true} />);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith('/api/throughput');
    });

    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  it('displays Insufficient data when API returns empty metrics', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        velocity: 0,
        cycleTimeByComplexity: [],
      }),
    });

    render(<ThroughputMetrics isRunning={true} />);

    await waitFor(() => {
      expect(screen.getByText(/Insufficient data/)).toBeInTheDocument();
    });
  });

  it('fetches on mount regardless of isRunning status', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => mockThroughputData,
    });

    render(<ThroughputMetrics isRunning={false} />);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith('/api/throughput');
    });
  });

  it('displays loading state initially', () => {
    (global.fetch as any).mockImplementationOnce(
      () => new Promise(() => {}) // Never resolves
    );

    render(<ThroughputMetrics isRunning={true} />);

    expect(screen.getByText(/Loading metrics/)).toBeInTheDocument();
  });

  it('shows idle status when not running', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => mockThroughputData,
    });

    render(<ThroughputMetrics isRunning={false} />);

    await waitFor(() => {
      expect(screen.getByText(/iteration idle/)).toBeInTheDocument();
    });
  });
});
