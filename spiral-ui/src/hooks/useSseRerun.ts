import { useState, useCallback } from 'react';

export interface SseMessage {
  type: 'log' | 'complete';
  content?: string;
  status?: 'passed' | 'failed' | 'error';
  duration?: number;
  timestamp?: string;
}

export function useSseRerun() {
  const [isRunning, setIsRunning] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [status, setStatus] = useState<'passed' | 'failed' | 'error' | null>(null);
  const [error, setError] = useState<string | null>(null);

  const rerun = useCallback((testId: string) => {
    setIsRunning(true);
    setLogs([]);
    setStatus(null);
    setError(null);

    try {
      const eventSource = new EventSource(`/api/tests/rerun/${testId}`);

      eventSource.onmessage = (event) => {
        try {
          const message: SseMessage = JSON.parse(event.data);

          if (message.type === 'log' && message.content) {
            setLogs((prev) => [...prev, message.content!]);
          } else if (message.type === 'complete') {
            setStatus(message.status || 'passed');
            setIsRunning(false);
            eventSource.close();
          }
        } catch (e) {
          console.error('Failed to parse SSE message:', e);
        }
      };

      eventSource.onerror = () => {
        setError('Connection lost');
        setIsRunning(false);
        eventSource.close();
      };
    } catch (e) {
      setError(`Failed to start re-run: ${String(e)}`);
      setIsRunning(false);
    }
  }, []);

  const reset = useCallback(() => {
    setLogs([]);
    setStatus(null);
    setError(null);
    setIsRunning(false);
  }, []);

  return {
    isRunning,
    logs,
    status,
    error,
    rerun,
    reset
  };
}
