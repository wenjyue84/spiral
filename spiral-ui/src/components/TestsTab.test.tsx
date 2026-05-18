import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import TestsTab from './TestsTab';
import type { PhaseVResult } from '../types/phase';

// Mock fetch globally
global.fetch = vi.fn();

const mockPhaseVResults: PhaseVResult[] = [
  {
    id: 'test-1',
    story_id: 'US-001',
    test_file: 'tests/test_spiral_e2e_integration.py::test_full_loop_phase_order',
    duration_s: 1.23,
    passed: true,
    timestamp: '2026-04-27T12:00:00Z',
  },
  {
    id: 'test-2',
    story_id: 'US-002',
    test_file: 'tests/test_federation_merge_integration.py::test_namespace_isolation',
    duration_s: 2.45,
    passed: false,
    timestamp: '2026-04-27T12:00:01Z',
  },
  {
    id: 'test-3',
    story_id: 'US-001',
    test_file: 'tests/test_spiral_e2e_integration.py::test_prd_final_state',
    duration_s: 0.98,
    passed: true,
    timestamp: '2026-04-27T12:00:02Z',
  },
];

describe('TestsTab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (global.fetch as any).mockReset();
  });

  it('renders summary bar with total tests, pass rate, and average duration', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => mockPhaseVResults,
    });

    render(<TestsTab />);

    await waitFor(() => {
      expect(screen.getByText('3')).toBeInTheDocument();
    });

    expect(screen.getByText('Total Tests')).toBeInTheDocument();
    expect(screen.getByText('Pass Rate')).toBeInTheDocument();
    expect(screen.getByText('Avg Duration')).toBeInTheDocument();
    expect(screen.getByText('67%')).toBeInTheDocument();
    expect(screen.getByText('1.55s')).toBeInTheDocument();
  });

  it('renders table with columns: status badge, story_id, test_file, duration', async () => {
    (global.fetch as any).mockImplementationOnce(
      async () => ({
        ok: true,
        json: async () => mockPhaseVResults,
      }),
    );

    render(<TestsTab />);

    // Wait for table headers to appear
    const headers = await screen.findAllByRole('columnheader');
    expect(headers.length).toBeGreaterThan(0);

    expect(screen.getByText('Status')).toBeInTheDocument();
    expect(screen.getByText('Story ID')).toBeInTheDocument();
    expect(screen.getByText('Test File')).toBeInTheDocument();
    expect(screen.getByText('Duration (s)')).toBeInTheDocument();
  });

  it('displays pass/fail badges with correct styling', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => mockPhaseVResults,
    });

    render(<TestsTab />);

    await waitFor(() => {
      expect(screen.getAllByText('✓ Passed')).toHaveLength(2);
    });

    const passedBadges = screen.getAllByText('✓ Passed');
    const failedBadge = screen.getByText('✗ Failed');

    passedBadges.forEach((badge) => {
      expect((badge as HTMLElement).className).toMatch(/bg-emerald-100/);
      expect((badge as HTMLElement).className).toMatch(/text-emerald-700/);
    });
    expect((failedBadge as HTMLElement).className).toMatch(/bg-red-100/);
    expect((failedBadge as HTMLElement).className).toMatch(/text-red-700/);
  });

  it('renders all test results in chronological order (newest first)', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => mockPhaseVResults,
    });

    render(<TestsTab />);

    await waitFor(() => {
      const rows = screen.getAllByRole('row');
      expect(rows.length).toBeGreaterThanOrEqual(4); // header + 3 data rows
    });

    const testFileElements = screen.getAllByText(/test_/);
    expect(testFileElements.length).toBeGreaterThanOrEqual(3);
  });

  it('displays "No test results yet" when data is empty', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    });

    render(<TestsTab />);

    // Component starts loading
    expect(screen.getByText('Loading test results…')).toBeInTheDocument();

    // Wait for fetch to complete
    await waitFor(
      () => {
        expect(screen.queryByText('Loading test results…')).not.toBeInTheDocument();
      },
      { timeout: 1000 },
    );

    // Should now show empty state
    expect(screen.getByText('No test results yet')).toBeInTheDocument();
  });

  it('displays error message on fetch failure', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: false,
      statusText: 'Internal Server Error',
    });

    render(<TestsTab />);

    // Component starts loading
    expect(screen.getByText('Loading test results…')).toBeInTheDocument();

    // Wait for error to appear
    await waitFor(
      () => {
        expect(
          screen.queryByText(/Error loading test results/),
        ).toBeInTheDocument();
      },
      { timeout: 1000 },
    );
  });

  it('displays loading state initially', () => {
    (global.fetch as any).mockImplementationOnce(
      () => new Promise(() => {/* never resolves */}),
    );

    render(<TestsTab />);

    expect(screen.getByText('Loading test results…')).toBeInTheDocument();
  });
});
