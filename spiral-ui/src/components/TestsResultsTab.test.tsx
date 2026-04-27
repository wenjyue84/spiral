import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import TestsResultsTab from './TestsResultsTab';

// Mock fetch
global.fetch = vi.fn();

const mockTestResults = [
  {
    id: 'test-1',
    name: 'example.test.ts',
    status: 'passed',
    duration: 1.23,
    file: 'results.tsv:1',
    timestamp: '2026-04-27T12:00:00Z'
  },
  {
    id: 'test-2',
    name: 'integration.test.ts',
    status: 'failed',
    duration: 2.45,
    file: 'results.tsv:2',
    timestamp: '2026-04-27T12:00:01Z'
  }
];

describe('TestsResultsTab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders table with columns: test name, status badge, duration, file, action', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      json: async () => mockTestResults
    });

    render(<TestsResultsTab />);

    await waitFor(() => {
      expect(screen.getByText('example.test.ts')).toBeInTheDocument();
    });

    expect(screen.getByText('Test Name')).toBeInTheDocument();
    expect(screen.getByText('Status')).toBeInTheDocument();
    expect(screen.getByText('Duration')).toBeInTheDocument();
    expect(screen.getByText('File')).toBeInTheDocument();
    expect(screen.getByText('Action')).toBeInTheDocument();
  });

  it('displays status badges with correct colors for passed/failed tests', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      json: async () => mockTestResults
    });

    render(<TestsResultsTab />);

    await waitFor(() => {
      expect(screen.getByText('example.test.ts')).toBeInTheDocument();
    });

    const passedBadge = screen.getByText('✓ Passed');
    const failedBadge = screen.getByText('✗ Failed');

    expect(passedBadge).toHaveClass('bg-emerald-100', 'text-emerald-700');
    expect(failedBadge).toHaveClass('bg-red-100', 'text-red-700');
  });

  it('formats duration correctly (seconds and milliseconds)', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      json: async () => mockTestResults
    });

    render(<TestsResultsTab />);

    await waitFor(() => {
      expect(screen.getByText('1.23s')).toBeInTheDocument();
      expect(screen.getByText('2.45s')).toBeInTheDocument();
    });
  });

  it('clicking Re-run button calls rerun with test ID', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      json: async () => mockTestResults
    });

    // Mock EventSource for SSE
    const mockClose = vi.fn();
    global.EventSource = vi.fn(() => ({
      onmessage: null,
      onerror: null,
      close: mockClose,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn()
    })) as any;

    render(<TestsResultsTab />);

    await waitFor(() => {
      expect(screen.getByText('example.test.ts')).toBeInTheDocument();
    });

    const rerunButtons = screen.getAllByRole('button');
    const firstRerunButton = rerunButtons[0];

    await userEvent.click(firstRerunButton);

    expect(global.EventSource).toHaveBeenCalledWith('/api/tests/rerun/test-1');
  });

  it('displays SSE log panel when test is selected', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      json: async () => mockTestResults
    });

    global.EventSource = vi.fn(() => ({
      onmessage: null,
      onerror: null,
      close: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn()
    })) as any;

    render(<TestsResultsTab />);

    await waitFor(() => {
      expect(screen.getByText('example.test.ts')).toBeInTheDocument();
    });

    const rerunButtons = screen.getAllByRole('button');
    await userEvent.click(rerunButtons[0]);

    await waitFor(() => {
      expect(screen.getByText('SSE Re-run Log')).toBeInTheDocument();
    });
  });

  it('shows empty state when no test results', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      json: async () => []
    });

    render(<TestsResultsTab />);

    await waitFor(() => {
      expect(screen.getByText('No test results yet')).toBeInTheDocument();
    });
  });

  it('shows error state when fetch fails', async () => {
    (global.fetch as any).mockRejectedValueOnce(new Error('Network error'));

    render(<TestsResultsTab />);

    await waitFor(() => {
      expect(screen.getByText(/Error:/)).toBeInTheDocument();
    });
  });
});
