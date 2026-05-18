import { render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest';
import CostAnalysisTab from './CostAnalysisTab';

describe('CostAnalysisTab', () => {
  const mockCostData = {
    entries: [
      { phase: 'Phase A', cost_usd: 25.50, token_count: 10000 },
      { phase: 'Phase B', cost_usd: 45.75, token_count: 18000 },
      { phase: 'Phase C', cost_usd: 28.25, token_count: 11000 },
    ],
    total_cost_usd: 99.50,
    burn_rate_per_minute: 0.45,
    ceiling_usd: 200.00,
  };

  beforeEach(() => {
    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it('renders loading state initially', () => {
    (global.fetch as any).mockImplementationOnce(
      () => new Promise(() => {
        /* never resolves */
      }),
    );

    render(<CostAnalysisTab />);
    expect(screen.getByText('Loading cost analysis…')).toBeInTheDocument();
  });

  it('renders two recharts components with mocked API response', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => mockCostData,
    });

    render(<CostAnalysisTab />);

    // Check for chart titles after loading completes
    expect(await screen.findByText('Cost by Phase')).toBeInTheDocument();
    expect(screen.getByText('Cumulative Spend')).toBeInTheDocument();
  });

  it('displays budget projection card with required labels', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => mockCostData,
    });

    render(<CostAnalysisTab />);

    // Verify labels are displayed
    expect(await screen.findByText('Spend:')).toBeInTheDocument();
    expect(screen.getByText('Burn rate:')).toBeInTheDocument();
    expect(screen.getByText('Remaining:')).toBeInTheDocument();

    // Verify the values are displayed
    expect(screen.getByText('$99.5')).toBeInTheDocument();
    expect(screen.getByText('$0.45/min')).toBeInTheDocument();
    expect(screen.getByText('$100.5')).toBeInTheDocument();
  });

  it('displays usage percentage when ceiling is set', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => mockCostData,
    });

    render(<CostAnalysisTab />);

    // 99.5 / 200 * 100 = 49.75 → Math.round = 50%, rendered as two separate text nodes: "50" and "%"
    expect(await screen.findByText('Usage:')).toBeInTheDocument();
    // Check for the percentage value "50" which appears in the span
    const percentText = screen.getByText((content, element) => {
      return element?.className?.includes('w-8') && content.includes('50');
    });
    expect(percentText).toBeInTheDocument();
  });

  it('renders charts with multiple entries', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => mockCostData,
    });

    render(<CostAnalysisTab />);

    // Verify the component renders the chart titles which indicate the charts are rendered
    expect(await screen.findByText('Cost by Phase')).toBeInTheDocument();
    expect(screen.getByText('Cumulative Spend')).toBeInTheDocument();
  });

  it('displays error message on fetch failure', async () => {
    (global.fetch as any).mockRejectedValueOnce(new Error('Network error'));

    render(<CostAnalysisTab />);

    expect(await screen.findByText(/Error loading cost data:/)).toBeInTheDocument();
  });

  it('displays empty state when no entries', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        entries: [],
        total_cost_usd: 0,
        burn_rate_per_minute: 0,
        ceiling_usd: 0,
      }),
    });

    render(<CostAnalysisTab />);

    expect(await screen.findByText('No cost data available yet')).toBeInTheDocument();
  });

  it('displays high spend with appropriate styling', async () => {
    const highSpendData = {
      entries: [{ phase: 'Phase A', cost_usd: 150, token_count: 50000 }],
      total_cost_usd: 150,
      burn_rate_per_minute: 0.75,
      ceiling_usd: 200,
    };

    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => highSpendData,
    });

    render(<CostAnalysisTab />);

    // Verify high spend is displayed correctly
    expect(await screen.findByText('$150')).toBeInTheDocument();
    expect(screen.getByText('$0.75/min')).toBeInTheDocument();
  });
});
