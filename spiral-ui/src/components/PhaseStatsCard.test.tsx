import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import type { RawEvent } from '../hooks/usePhaseStats';

// We need to mock the usePhaseStats hook before importing the component
vi.mock('../hooks/usePhaseStats', () => ({
  usePhaseStats: vi.fn(),
  parseEventLog: vi.fn(),
  computePhaseStats: vi.fn(),
}));

// Import component and hook after mocking
import PhaseStatsCard from './PhaseStatsCard';
import { usePhaseStats } from '../hooks/usePhaseStats';

// Mock spiral_events data
const mockEvents: RawEvent[] = [
  // Phase A - AI Suggest (8 events, 7 successful)
  { phase: 'A', event_type: 'phase_entered', duration: 10 },
  { phase: 'A', status: 'success', duration: 8 },
  { phase: 'A', status: 'success', duration: 12 },
  { phase: 'A', status: 'success', duration: 9 },
  { phase: 'A', status: 'success', duration: 11 },
  { phase: 'A', status: 'success', duration: 10 },
  { phase: 'A', status: 'success', duration: 8 },
  { phase: 'A', status: 'failed', duration: 5 },

  // Phase R - Research (10 events, 10 successful = 100%)
  { phase: 'R', status: 'success', duration: 30 },
  { phase: 'R', status: 'success', duration: 28 },
  { phase: 'R', status: 'success', duration: 32 },
  { phase: 'R', status: 'success', duration: 29 },
  { phase: 'R', status: 'success', duration: 31 },
  { phase: 'R', status: 'success', duration: 30 },
  { phase: 'R', status: 'success', duration: 27 },
  { phase: 'R', status: 'success', duration: 33 },
  { phase: 'R', status: 'success', duration: 29 },
  { phase: 'R', status: 'success', duration: 31 },

  // Phase T - Test Synth (5 events, 4 successful = 80%)
  { phase: 'T', status: 'success', duration: 15 },
  { phase: 'T', status: 'success', duration: 14 },
  { phase: 'T', status: 'success', duration: 16 },
  { phase: 'T', status: 'success', duration: 15 },
  { phase: 'T', status: 'failed', duration: 20 },

  // Phase S - Story Valid (6 events, 6 successful = 100%)
  { phase: 'S', status: 'success', duration: 5 },
  { phase: 'S', status: 'success', duration: 6 },
  { phase: 'S', status: 'success', duration: 5 },
  { phase: 'S', status: 'success', duration: 7 },
  { phase: 'S', status: 'success', duration: 5 },
  { phase: 'S', status: 'success', duration: 6 },

  // Phase E - Enrichment (4 events, 3 successful = 75%)
  { phase: 'E', status: 'success', duration: 20 },
  { phase: 'E', status: 'success', duration: 22 },
  { phase: 'E', status: 'success', duration: 21 },
  { phase: 'E', status: 'failed', duration: 25 },

  // Phase M - Merge (3 events, 3 successful = 100%)
  { phase: 'M', status: 'success', duration: 2 },
  { phase: 'M', status: 'success', duration: 3 },
  { phase: 'M', status: 'success', duration: 2 },

  // Phase I - Implement (7 events, 5 successful = 71.4%)
  { phase: 'I', status: 'success', duration: 60 },
  { phase: 'I', status: 'success', duration: 55 },
  { phase: 'I', status: 'success', duration: 62 },
  { phase: 'I', status: 'success', duration: 58 },
  { phase: 'I', status: 'success', duration: 61 },
  { phase: 'I', status: 'failed', duration: 70 },
  { phase: 'I', status: 'failed', duration: 65 },

  // Phase V - Validate (2 events, 1 successful = 50%)
  { phase: 'V', status: 'success', duration: 10 },
  { phase: 'V', status: 'failed', duration: 12 },
];

describe('PhaseStatsCard', () => {
  const defaultStats = [
    { phase: 'A', label: 'AI Suggest', successRate: 87.5, successCount: 7, totalCount: 8, avgDuration: 9 },
    { phase: 'R', label: 'Research', successRate: 100, successCount: 10, totalCount: 10, avgDuration: 30 },
    { phase: 'T', label: 'Test Synth', successRate: 80, successCount: 4, totalCount: 5, avgDuration: 15 },
    { phase: 'S', label: 'Story Valid', successRate: 100, successCount: 6, totalCount: 6, avgDuration: 6 },
    { phase: 'E', label: 'Enrichment', successRate: 75, successCount: 3, totalCount: 4, avgDuration: 21 },
    { phase: 'M', label: 'Merge', successRate: 100, successCount: 3, totalCount: 3, avgDuration: 2 },
    { phase: 'I', label: 'Implement', successRate: 71.4, successCount: 5, totalCount: 7, avgDuration: 60 },
    { phase: 'V', label: 'Validate', successRate: 50, successCount: 1, totalCount: 2, avgDuration: 11 },
  ];

  beforeEach(() => {
    // Mock usePhaseStats hook with default stats
    vi.mocked(usePhaseStats).mockReturnValue({
      stats: defaultStats,
      isLoading: false,
      eventCount: 52,
    });
  });

  it('renders grid title and legend', () => {
    render(<PhaseStatsCard projectName="test-project" initialEvents={mockEvents} />);

    expect(screen.getByText('Phase Success Rates')).toBeInTheDocument();
    expect(screen.getByText(/Per-phase execution metrics/)).toBeInTheDocument();
    expect(screen.getByText('Excellent (≥90%)')).toBeInTheDocument();
    expect(screen.getByText(/Good \(70–90%\)/)).toBeInTheDocument();
    expect(screen.getByText(/Needs Work \(<70%\)/)).toBeInTheDocument();
  });

  it('renders 8 phase cards (A-V) in 4x2 grid', () => {
    render(<PhaseStatsCard projectName="test-project" initialEvents={mockEvents} />);

    const phases = ['A', 'R', 'T', 'S', 'E', 'M', 'I', 'V'];
    for (const phase of phases) {
      expect(screen.getByText(phase)).toBeInTheDocument();
    }
  });

  it('displays success rate percentage for each phase', () => {
    render(<PhaseStatsCard projectName="test-project" initialEvents={mockEvents} />);

    expect(screen.getByText('87.5%')).toBeInTheDocument();
    expect(screen.getAllByText('100.0%').length).toBeGreaterThanOrEqual(3); // R, S, M have 100%
    expect(screen.getByText('80.0%')).toBeInTheDocument();
    expect(screen.getByText('75.0%')).toBeInTheDocument();
    expect(screen.getByText('71.4%')).toBeInTheDocument();
    expect(screen.getByText('50.0%')).toBeInTheDocument();
  });

  it('displays story counts (passed/total)', () => {
    const { container } = render(
      <PhaseStatsCard projectName="test-project" initialEvents={mockEvents} />,
    );

    // Check for the presence of expected count values in the page
    const allText = container.textContent || '';
    expect(allText).toContain('stories passed'); // Verify counts are displayed
    expect(allText).toContain('7'); // Phase A: 7 passed
    expect(allText).toContain('10'); // Phase R: 10 passed
    expect(allText).toContain('4'); // Phase T: 4 passed
  });

  it('displays average duration in seconds', () => {
    render(<PhaseStatsCard projectName="test-project" initialEvents={mockEvents} />);

    expect(screen.getByText('9s avg')).toBeInTheDocument(); // Phase A
    expect(screen.getByText('30s avg')).toBeInTheDocument(); // Phase R
    expect(screen.getByText('60s avg')).toBeInTheDocument(); // Phase I
  });

  it('color-codes cards: green for >90%, yellow for 70-90%, red for <70%', () => {
    const { container } = render(
      <PhaseStatsCard projectName="test-project" initialEvents={mockEvents} />,
    );

    const cards = container.querySelectorAll('[class*="rounded-lg"]');
    expect(cards.length).toBeGreaterThan(0);

    // Check that green cards exist (>90%)
    const greenCards = Array.from(cards).filter(card =>
      (card as HTMLElement).className.includes('bg-green-50'),
    );
    expect(greenCards.length).toBeGreaterThan(0); // R, S, M

    // Check that yellow cards exist (70-90%)
    const yellowCards = Array.from(cards).filter(card =>
      (card as HTMLElement).className.includes('bg-yellow-50'),
    );
    expect(yellowCards.length).toBeGreaterThan(0); // A, T, E, I

    // Check that red cards exist (<70%)
    const redCards = Array.from(cards).filter(card =>
      (card as HTMLElement).className.includes('bg-red-50'),
    );
    expect(redCards.length).toBeGreaterThan(0); // V
  });

  it('shows total event count in header', () => {
    render(<PhaseStatsCard projectName="test-project" initialEvents={mockEvents} />);

    // The total should be the sum of all totalCount values from stats
    // 8 + 10 + 5 + 6 + 4 + 3 + 7 + 2 = 45
    expect(screen.getByText('45')).toBeInTheDocument();
  });

  it('renders empty state when no events provided', () => {
    // Use a fresh mock implementation for this test
    vi.mocked(usePhaseStats).mockImplementation(() => ({
      stats: [],
      isLoading: false,
      eventCount: 0,
    }));

    render(<PhaseStatsCard projectName="test-project" initialEvents={[]} />);

    expect(screen.getByText('No phase data available yet')).toBeInTheDocument();
  });

  it('renders loading state when events are being loaded', () => {
    // Use a fresh mock implementation for this test
    vi.mocked(usePhaseStats).mockImplementation(() => ({
      stats: [],
      isLoading: true,
      eventCount: 0,
    }));

    render(<PhaseStatsCard projectName="test-project" initialEvents={[]} />);

    expect(screen.getByText('Loading phase statistics...')).toBeInTheDocument();
  });
});
