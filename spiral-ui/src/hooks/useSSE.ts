import { useEffect, useRef } from 'react';

export interface SSEEvent {
  event_type?: string;
  event?: string;
  type?: string;
  phase?: string;
  iteration?: number;
  run_id?: string;
  [key: string]: unknown;
}

const MAX_RETRIES = 5;
const BASE_DELAY = 1000;
const MAX_DELAY = 30_000;

/**
 * useSSE — Subscribe to the /api/events SSE endpoint for real-time spiral event streaming.
 *
 * Wraps EventSource with exponential backoff reconnection (max 5 retries, cap 30s).
 * Calls `onEvent` for each parsed JSON event from the stream.
 */
export function useSSE(
  projectName: string | undefined,
  onEvent: (event: SSEEvent) => void,
) {
  const onEventRef = useRef(onEvent);
  useEffect(() => { onEventRef.current = onEvent; });

  useEffect(() => {
    if (!projectName) return;

    let retryCount = 0;
    let es: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let disposed = false;

    function connect() {
      if (disposed) return;

      const url = `/api/events?name=${encodeURIComponent(projectName)}`;
      es = new EventSource(url);

      es.onmessage = (msg) => {
        retryCount = 0;
        try {
          const parsed = JSON.parse(msg.data) as SSEEvent;
          onEventRef.current(parsed);
        } catch { /* skip malformed data */ }
      };

      es.onerror = () => {
        es?.close();
        es = null;
        if (disposed || retryCount >= MAX_RETRIES) return;

        const delay = Math.min(BASE_DELAY * Math.pow(2, retryCount), MAX_DELAY);
        retryCount += 1;
        timer = setTimeout(connect, delay);
      };
    }

    connect();

    return () => {
      disposed = true;
      es?.close();
      es = null;
      if (timer) clearTimeout(timer);
    };
  }, [projectName]);
}
