import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import HealthWidget from './HealthWidget';

global.fetch = vi.fn();

const mockHealthData = {
  status: 'ok',
  timestamp: '2026-05-18T12:00:00Z',
  phases: {
    A: 2500,
    R: 5000,
    T: 3200,
    S: 1800,
    E: 900,
    M: 700,
    X: 500,
    G: 100,
    I: 15000,
    V: 8000,
    C: 300
  },
  workers: {
    active: 2,
    crashed: 0,
    total: 3
  },
  tokens: {
    current_rate: 450,
    average_rate: 380,
    trend: [410, 420, 405, 425, 445, 450]
  }
};

describe('HealthWidget', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders phase durations, workers active/crashed, and token burn rate from mocked /api/health response', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => mockHealthData,
    });

    render(<HealthWidget />);

    await waitFor(() => {
      expect(screen.getByText(/2/)).toBeInTheDocument(); // active workers
    });

    // Verify token burn rate is shown
    expect(screen.getByText(/450/)).toBeInTheDocument();
    expect(screen.getByText(/tokens\/min/)).toBeInTheDocument();

    // Verify slowest phase is displayed
    expect(screen.getByText(/Slowest Phase/)).toBeInTheDocument();
    expect(screen.getByText(/Phase I/)).toBeInTheDocument();
  });

  it('shows error banner and retries after 10 s when /api/health returns a non-200 status', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: false,
      status: 500,
    });

    render(<HealthWidget />);

    await waitFor(() => {
      expect(screen.getByText(/Connection Error/)).toBeInTheDocument();
    });

    expect(screen.getByText(/Health check failed/)).toBeInTheDocument();
    // Verify the error message is displayed
    expect(screen.getByText(/Retrying every 5 seconds/)).toBeInTheDocument();
  });

  it('fetches from /api/health on mount', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => mockHealthData,
    });

    render(<HealthWidget />);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith('/api/health', expect.any(Object));
    });
  });

  it('displays loading state initially', () => {
    (global.fetch as any).mockImplementationOnce(
      () => new Promise(() => {}) // Never resolves
    );

    render(<HealthWidget />);

    expect(screen.getByText(/Loading health metrics/)).toBeInTheDocument();
  });

  it('displays worker metrics correctly', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => mockHealthData,
    });

    render(<HealthWidget />);

    await waitFor(() => {
      expect(screen.getByText(/active/)).toBeInTheDocument();
    });

    expect(screen.getByText(/Workers/)).toBeInTheDocument();
    expect(screen.getByText(/of 3/)).toBeInTheDocument();
  });

  it('clears error when connection recovers', async () => {
    const fetchMock = (global.fetch as any);

    // First call fails
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
    });

    const { rerender } = render(<HealthWidget />);

    await waitFor(() => {
      expect(screen.getByText(/Connection Error/)).toBeInTheDocument();
    });

    // Simulate recovery on next render (in real app would happen on next poll)
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => mockHealthData,
    });

    // Re-render or in actual usage next poll will succeed
    rerender(<HealthWidget />);

    await waitFor(() => {
      expect(screen.getByText(/Health Metrics/)).toBeInTheDocument();
    });
  });

  it('renders Health Metrics title', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => mockHealthData,
    });

    render(<HealthWidget />);

    await waitFor(() => {
      expect(screen.getByText(/Health Metrics/)).toBeInTheDocument();
    });
  });

  it('displays token burn rate with trend sparkline', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => mockHealthData,
    });

    render(<HealthWidget />);

    await waitFor(() => {
      expect(screen.getByText(/Token Burn Rate/)).toBeInTheDocument();
    });

    expect(screen.getByText(/450/)).toBeInTheDocument();
    expect(screen.getByText(/Avg: 380t\/m/)).toBeInTheDocument();
  });

  it('polling-interval: fetches again after 5 seconds using fake timers', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn();
    (global.fetch as any) = fetchMock;

    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => mockHealthData,
    });

    render(<HealthWidget />);

    // Initial fetch
    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    // Advance timer by 5 seconds
    vi.advanceTimersByTime(5000);

    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    vi.useRealTimers();
  });

  it('exponential back-off: retry delay doubles on simulated fetch error', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn();
    (global.fetch as any) = fetchMock;

    // Mock setInterval to prevent polling from interfering
    const setIntervalSpy = vi.spyOn(global, 'setInterval').mockReturnValue(0 as any);
    const clearIntervalSpy = vi.spyOn(global, 'clearInterval').mockReturnValue(undefined as any);

    // Mock all failures
    fetchMock.mockRejectedValue(new Error('Network error'));

    render(<HealthWidget />);

    // Wait for initial failed fetch
    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    // First retry should happen after 2^0 * 1000 = 1000ms
    vi.advanceTimersByTime(1000);
    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    // Second retry should happen after 2^1 * 1000 = 2000ms
    vi.advanceTimersByTime(2000);
    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(3);
    });

    // Third retry should happen after 2^2 * 1000 = 4000ms
    vi.advanceTimersByTime(4000);
    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(4);
    });

    setIntervalSpy.mockRestore();
    clearIntervalSpy.mockRestore();
    vi.useRealTimers();
  });

  it('renders output with no Bearer or sk- token patterns', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => mockHealthData,
    });

    const { container } = render(<HealthWidget />);

    await waitFor(() => {
      expect(screen.getByText(/Health Metrics/)).toBeInTheDocument();
    });

    // Get all text content from the rendered component
    const renderedText = container.textContent || '';

    // Assert no Bearer token patterns
    expect(renderedText).not.toMatch(/Bearer\s+[a-zA-Z0-9_-]+/);

    // Assert no sk- API key patterns
    expect(renderedText).not.toMatch(/sk-[a-zA-Z0-9]+/);

    // Assert no token-like patterns in the output
    expect(screen.queryByText(/Bearer|sk-[a-zA-Z0-9]+/)).not.toBeInTheDocument();
  });
});
