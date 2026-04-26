import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom/vitest';
import TestsTab from './TestsTab';

// Mock the useTestResults hook
vi.mock('../hooks/useTestResults', () => ({
  useTestResults: vi.fn(),
}));

// Mock the TestDetailModal
vi.mock('../components/TestDetailModal', () => ({
  default: ({ story, onClose }: { story: import('../hooks/useTestResults').TestSummary | null; onClose: () => void }) => {
    if (!story) return null;
    return (
      <div data-testid="test-detail-modal">
        <div>{story.story_id}</div>
        <button onClick={onClose}>Close</button>
      </div>
    );
  },
}));

const mockTestResults = [
  {
    story_id: 'US-1001',
    test_status: 'passed',
    test_count: 5,
    file_touch_ok: true,
    coverage_pct: 95,
  },
  {
    story_id: 'US-1002',
    test_status: 'failed',
    test_count: 3,
    file_touch_ok: false,
    coverage_pct: 78,
  },
];

describe('TestsTab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders a table with columns: Story ID, Test Status, Test Count, File-Touch OK, Coverage %', async () => {
    const { useTestResults } = await import('../hooks/useTestResults');
    vi.mocked(useTestResults).mockReturnValue({
      data: mockTestResults,
      loading: false,
      error: null,
    });

    render(<TestsTab />);

    expect(screen.getByText('Story ID')).toBeInTheDocument();
    expect(screen.getByText('Test Status')).toBeInTheDocument();
    expect(screen.getByText('Test Count')).toBeInTheDocument();
    expect(screen.getByText('File-Touch OK')).toBeInTheDocument();
    expect(screen.getByText('Coverage %')).toBeInTheDocument();
  });

  it('displays test results in table rows', async () => {
    const { useTestResults } = await import('../hooks/useTestResults');
    vi.mocked(useTestResults).mockReturnValue({
      data: mockTestResults,
      loading: false,
      error: null,
    });

    render(<TestsTab />);

    expect(screen.getByText('US-1001')).toBeInTheDocument();
    expect(screen.getByText('US-1002')).toBeInTheDocument();
    expect(screen.getByText('passed')).toBeInTheDocument();
    expect(screen.getByText('failed')).toBeInTheDocument();
  });

  it('clicking a story row opens TestDetailModal', async () => {
    const { useTestResults } = await import('../hooks/useTestResults');
    vi.mocked(useTestResults).mockReturnValue({
      data: mockTestResults,
      loading: false,
      error: null,
    });

    const user = userEvent.setup();
    render(<TestsTab />);

    const storyRow = screen.getAllByText('US-1001')[0].closest('tr');
    expect(storyRow).toBeInTheDocument();

    if (storyRow) {
      await user.click(storyRow);
    }

    await waitFor(() => {
      expect(screen.getByTestId('test-detail-modal')).toBeInTheDocument();
    });
  });

  it('handles loading state', async () => {
    const { useTestResults } = await import('../hooks/useTestResults');
    vi.mocked(useTestResults).mockReturnValue({
      data: [],
      loading: true,
      error: null,
    });

    render(<TestsTab />);

    expect(screen.getByText('Loading test results…')).toBeInTheDocument();
  });

  it('handles error state', async () => {
    const { useTestResults } = await import('../hooks/useTestResults');
    vi.mocked(useTestResults).mockReturnValue({
      data: [],
      loading: false,
      error: 'Failed to fetch',
    });

    render(<TestsTab />);

    expect(screen.getByText(/Error loading test results/)).toBeInTheDocument();
    expect(screen.getByText(/Failed to fetch/)).toBeInTheDocument();
  });

  it('handles empty results', async () => {
    const { useTestResults } = await import('../hooks/useTestResults');
    vi.mocked(useTestResults).mockReturnValue({
      data: [],
      loading: false,
      error: null,
    });

    render(<TestsTab />);

    expect(screen.getByText('No test results yet')).toBeInTheDocument();
    expect(
      screen.getByText('Run SPIRAL to generate test verification events')
    ).toBeInTheDocument();
  });

  it('renders file_touch_ok as checkmark when true', async () => {
    const { useTestResults } = await import('../hooks/useTestResults');
    vi.mocked(useTestResults).mockReturnValue({
      data: mockTestResults,
      loading: false,
      error: null,
    });

    render(<TestsTab />);

    const checkmarks = screen.getAllByText('✓');
    expect(checkmarks.length).toBeGreaterThan(0);
  });

  it('renders file_touch_ok as X when false', async () => {
    const { useTestResults } = await import('../hooks/useTestResults');
    vi.mocked(useTestResults).mockReturnValue({
      data: mockTestResults,
      loading: false,
      error: null,
    });

    render(<TestsTab />);

    const xmarks = screen.getAllByText('✗');
    expect(xmarks.length).toBeGreaterThan(0);
  });
});
