import { useEffect, useRef } from 'react';

interface SseLogPanelProps {
  logs: string[];
  isRunning: boolean;
  status: 'passed' | 'failed' | 'error' | null;
  error: string | null;
}

export default function SseLogPanel({
  logs,
  isRunning,
  status,
  error
}: SseLogPanelProps) {
  const logRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [logs]);

  return (
    <div className="w-full h-full flex flex-col bg-slate-950 rounded border border-slate-700">
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-700 bg-slate-900">
        <span className="text-xs font-mono text-slate-400">SSE Re-run Log</span>
        {isRunning && (
          <span className="text-xs text-slate-400 flex items-center gap-1">
            <span className="animate-pulse">●</span> Running
          </span>
        )}
        {status === 'passed' && (
          <span className="text-xs text-emerald-400 font-semibold">✓ Passed</span>
        )}
        {status === 'failed' && (
          <span className="text-xs text-red-400 font-semibold">✗ Failed</span>
        )}
      </div>

      <pre
        ref={logRef}
        className="flex-1 overflow-y-auto p-3 text-xs font-mono text-slate-300 whitespace-pre-wrap break-all"
      >
        {logs.length === 0 && !isRunning && !error && (
          <span className="text-slate-500">Click "Re-run" to start…</span>
        )}
        {logs.map((log, idx) => (
          <div key={idx}>{log}</div>
        ))}
        {error && <div className="text-red-400 mt-2">Error: {error}</div>}
      </pre>
    </div>
  );
}
