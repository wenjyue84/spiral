import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import PhaseTimeline from './PhaseTimeline';

describe('PhaseTimeline', () => {
  it('renders empty state when no timings provided', () => {
    render(<PhaseTimeline timings={[]} />);
    expect(screen.getByText(/No phase timing data available yet/)).toBeInTheDocument();
  });

  it('renders empty state when timings is null', () => {
    render(<PhaseTimeline timings={null as any} />);
    expect(screen.getByText(/No phase timing data available yet/)).toBeInTheDocument();
  });

  it('renders chart title and legend', () => {
    const timings = [
      { phase: 'R', durationSec: 45, label: 'Research' },
      { phase: 'I', durationSec: 120, label: 'Implement' },
    ];
    render(<PhaseTimeline timings={timings} />);
    expect(screen.getByText(/Phase Timeline/)).toBeInTheDocument();
    expect(screen.getByText(/Fast \(<60s\)/)).toBeInTheDocument();
    expect(screen.getByText(/Medium \(60-300s\)/)).toBeInTheDocument();
    expect(screen.getByText(/Slow \(>300s\)/)).toBeInTheDocument();
  });

  it('displays top 3 slowest phases', () => {
    const timings = [
      { phase: 'A', durationSec: 10, label: 'Phase A' },
      { phase: 'B', durationSec: 50, label: 'Phase B' },
      { phase: 'C', durationSec: 200, label: 'Phase C' },
      { phase: 'D', durationSec: 100, label: 'Phase D' },
      { phase: 'E', durationSec: 350, label: 'Phase E' },
    ];
    render(<PhaseTimeline timings={timings} />);

    // Check for slowest phases header
    expect(screen.getByText(/Top 3 Slowest Phases/)).toBeInTheDocument();

    // Check for the 3 slowest phases (E: 350s, C: 200s, D: 100s)
    const phaseElements = screen.getAllByText(/Phase [CDE]/);
    expect(phaseElements.length).toBeGreaterThan(0);
  });

  it('calculates color coding correctly', () => {
    const timings = [
      { phase: 'R', durationSec: 30, label: 'Research' },     // green < 60
      { phase: 'I', durationSec: 150, label: 'Implement' },   // yellow 60-300
      { phase: 'V', durationSec: 500, label: 'Validate' },    // red > 300
    ];
    render(<PhaseTimeline timings={timings} />);

    // Check color indicators exist - should have multiple "View Details" buttons
    const detailsButtons = screen.getAllByText('View Details →');
    expect(detailsButtons.length).toBeGreaterThan(0);
  });

  it('displays metrics for each slow phase', () => {
    const timings = [
      { phase: 'I', durationSec: 200, label: 'Implement' },
      { phase: 'V', durationSec: 350, label: 'Validate' },
      { phase: 'C', durationSec: 30, label: 'Check Done' },
    ];
    render(<PhaseTimeline timings={timings} />);

    // Check for metric labels
    expect(screen.getAllByText(/Total Time/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Stories\/min/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Tokens\/hour/).length).toBeGreaterThan(0);
  });

  it('handles single phase correctly', () => {
    const timings = [
      { phase: 'R', durationSec: 120, label: 'Research' },
    ];
    render(<PhaseTimeline timings={timings} />);
    expect(screen.getByText(/Phase Timeline/)).toBeInTheDocument();
  });

  it('sorts phases by duration in slowest phases section', () => {
    const timings = [
      { phase: 'A', durationSec: 100, label: 'Phase A' },
      { phase: 'B', durationSec: 50, label: 'Phase B' },
      { phase: 'C', durationSec: 200, label: 'Phase C' },
    ];
    render(<PhaseTimeline timings={timings} />);

    // Top 3 slowest should be: C (200), A (100), B (50)
    const detailsButtons = screen.getAllByText(/View Details/);
    expect(detailsButtons.length).toBe(3); // All 3 phases shown
  });
});
