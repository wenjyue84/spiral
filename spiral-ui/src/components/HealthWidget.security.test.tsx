import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import HealthWidget from './HealthWidget';

global.fetch = vi.fn();

describe('HealthWidget security', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('401 response renders safe error message with no token in DOM', async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: false,
      status: 401,
      text: async () => 'Unauthorized: Bearer sk-ant-secret-token-abc123',
    });

    const { container } = render(<HealthWidget />);

    await waitFor(() => {
      expect(screen.getByText(/Connection Error/)).toBeInTheDocument();
    });

    const dom = container.textContent ?? '';

    // Error message is generic — status code only, no response body
    expect(screen.getByText(/Health check failed with status 401/)).toBeInTheDocument();

    // No auth token patterns leaked into rendered output
    expect(dom).not.toMatch(/Bearer\s+[a-zA-Z0-9_-]+/);
    expect(dom).not.toMatch(/sk-[a-zA-Z0-9_-]+/);
    expect(dom).not.toMatch(/secret[-_]token/i);
    expect(dom).not.toContain('Unauthorized');
  });

  it('403 response renders safe error message with no token content in DOM', async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: false,
      status: 403,
      text: async () => 'Forbidden: token=sk-ant-api03-mysecretvalue',
    });

    const { container } = render(<HealthWidget />);

    await waitFor(() => {
      expect(screen.getByText(/Connection Error/)).toBeInTheDocument();
    });

    const dom = container.textContent ?? '';

    // Only the safe status message is shown
    expect(screen.getByText(/Health check failed with status 403/)).toBeInTheDocument();

    // Response body with token is never rendered
    expect(dom).not.toMatch(/sk-ant-[a-zA-Z0-9_-]+/);
    expect(dom).not.toMatch(/token=[a-zA-Z0-9_-]+/i);
    expect(dom).not.toContain('Forbidden');
    expect(dom).not.toMatch(/mysecretvalue/i);
  });

  it('exponential back-off fires on error without leaking response body', async () => {
    vi.useFakeTimers();

    const fetchMock = vi.fn();
    (global.fetch as ReturnType<typeof vi.fn>) = fetchMock;

    const sensitiveBody = 'Authorization: Bearer sk-ant-sensitive-123';
    fetchMock.mockRejectedValue(new Error(`Network error: ${sensitiveBody}`));

    const setIntervalSpy = vi.spyOn(global, 'setInterval').mockReturnValue(0 as unknown as ReturnType<typeof setInterval>);
    const clearIntervalSpy = vi.spyOn(global, 'clearInterval').mockReturnValue(undefined);

    const { container } = render(<HealthWidget />);

    // Wait for initial failed fetch
    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    // Advance time: first retry at 1s (2^0 * 1000ms)
    vi.advanceTimersByTime(1000);
    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    // Advance time: second retry at 2s (2^1 * 1000ms)
    vi.advanceTimersByTime(2000);
    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(3);
    });

    // Back-off is running — verify no sensitive data in the DOM
    const dom = container.textContent ?? '';
    expect(dom).not.toMatch(/Bearer\s+[a-zA-Z0-9_-]+/);
    expect(dom).not.toMatch(/sk-ant-[a-zA-Z0-9_-]+/);
    expect(dom).not.toContain('sensitive-123');
    expect(dom).not.toMatch(/Authorization/i);

    setIntervalSpy.mockRestore();
    clearIntervalSpy.mockRestore();
    vi.useRealTimers();
  });
});
