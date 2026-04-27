import { useState, useEffect } from 'react';
import { useSseRerun } from '../hooks/useSseRerun';
import SseLogPanel from './SseLogPanel';

interface TestResult {
  id: string;
  name: string;
  status: 'passed' | 'failed' | 'error' | 'unknown';
  duration: number;
  file: string;
  timestamp: string;
}

export default function TestsResultsTab() {
  const [tests, setTests] = useState<TestResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTestId, setSelectedTestId] = useState<string | null>(null);
  const { isRunning, logs, status, error: sseError, rerun, reset } = useSseRerun();

  useEffect(() => {
    fetch('/api/tests/latest')
      .then((res) => res.json())
      .then((data: TestResult[]) => {
        setTests(data);
        setLoading(false);
      })
      .catch((e) => {
        setError(String(e));
        setLoading(false);
      });
  }, []);

  const handleRerun = (testId: string) => {
    setSelectedTestId(testId);
    reset();
    rerun(testId);
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'passed':
        return <span className="px-2 py-1 rounded text-xs font-semibold bg-emerald-100 text-emerald-700">✓ Passed</span>;
      case 'failed':
        return <span className="px-2 py-1 rounded text-xs font-semibold bg-red-100 text-red-700">✗ Failed</span>;
      case 'error':
        return <span className="px-2 py-1 rounded text-xs font-semibold bg-orange-100 text-orange-700">! Error</span>;
      default:
        return <span className="px-2 py-1 rounded text-xs font-semibold bg-slate-100 text-slate-700">? Unknown</span>;
    }
  };

  const formatDuration = (seconds: number) => {
    if (seconds < 1) return `${(seconds * 1000).toFixed(0)}ms`;
    return `${seconds.toFixed(2)}s`;
  };

  if (loading) {
    return <div className="p-6 text-sm text-slate-500">Loading test results…</div>;
  }

  if (error) {
    return <div className="p-6 text-sm text-red-500">Error: {error}</div>;
  }

  if (tests.length === 0) {
    return (
      <div className="p-6 text-center text-slate-500">
        <div className="text-3xl mb-2">🧪</div>
        <div className="text-sm font-medium">No test results yet</div>
        <div className="text-xs mt-1 text-slate-400">Run tests to see results here</div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col gap-4 p-4">
      {/* Test Results Table */}
      <div className="flex-1 overflow-hidden flex flex-col">
        <div className="overflow-auto flex-1">
          <table className="w-full border-collapse text-sm">
            <thead className="sticky top-0 bg-slate-100 border-b border-slate-300">
              <tr>
                <th className="px-4 py-2 text-left font-semibold text-slate-700 border-r border-slate-300">
                  Test Name
                </th>
                <th className="px-4 py-2 text-left font-semibold text-slate-700 border-r border-slate-300">
                  Status
                </th>
                <th className="px-4 py-2 text-left font-semibold text-slate-700 border-r border-slate-300">
                  Duration
                </th>
                <th className="px-4 py-2 text-left font-semibold text-slate-700 border-r border-slate-300">
                  File
                </th>
                <th className="px-4 py-2 text-center font-semibold text-slate-700">
                  Action
                </th>
              </tr>
            </thead>
            <tbody>
              {tests.map((test) => (
                <tr
                  key={test.id}
                  className="border-b border-slate-200 hover:bg-slate-50 transition-colors"
                >
                  <td className="px-4 py-3 font-mono text-slate-700 border-r border-slate-200">
                    {test.name}
                  </td>
                  <td className="px-4 py-3 border-r border-slate-200">
                    {getStatusBadge(test.status)}
                  </td>
                  <td className="px-4 py-3 text-slate-600 border-r border-slate-200">
                    {formatDuration(test.duration)}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500 border-r border-slate-200 font-mono">
                    {test.file}
                  </td>
                  <td className="px-4 py-3 text-center">
                    <button
                      onClick={() => handleRerun(test.id)}
                      disabled={isRunning && selectedTestId === test.id}
                      className={`text-xs px-3 py-1 rounded font-semibold transition-colors ${
                        isRunning && selectedTestId === test.id
                          ? 'bg-slate-200 text-slate-400 cursor-not-allowed'
                          : 'bg-blue-600 hover:bg-blue-700 text-white'
                      }`}
                    >
                      {isRunning && selectedTestId === test.id ? '⏳' : '🔄'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* SSE Log Panel */}
      {selectedTestId && (
        <div className="h-64 border-t border-slate-300 pt-4">
          <SseLogPanel
            logs={logs}
            isRunning={isRunning}
            status={status}
            error={sseError}
          />
        </div>
      )}
    </div>
  );
}
