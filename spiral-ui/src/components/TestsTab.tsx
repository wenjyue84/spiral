import { useMemo } from 'react';
import { usePhaseVResults } from '../hooks/usePhaseVResults';
import type { PhaseVResult } from '../types/phase';

export default function TestsTab() {
  const { data, isLoading, error } = usePhaseVResults();

  const results = useMemo(() => {
    if (!data) return [];
    return data.sort(
      (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
    );
  }, [data]);

  const summary = useMemo(() => {
    if (results.length === 0) {
      return { totalTests: 0, passRate: 0, avgDuration: 0 };
    }
    const passed = results.filter((r) => r.passed).length;
    const totalDuration = results.reduce((sum, r) => sum + r.duration_s, 0);
    return {
      totalTests: results.length,
      passRate: Math.round((passed / results.length) * 100),
      avgDuration: Math.round((totalDuration / results.length) * 100) / 100,
    };
  }, [results]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500 text-sm">
        Loading test results…
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 text-sm text-red-500">
        Error loading test results: {(error as Error).message}
      </div>
    );
  }

  if (results.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400 text-sm flex-col gap-2">
        <span className="text-3xl">🧪</span>
        <span>No test results yet</span>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col overflow-hidden bg-slate-50">
      {/* Summary Bar */}
      <div className="bg-white border-b border-slate-200 px-6 py-4 flex-shrink-0">
        <div className="flex items-center gap-8">
          <div className="flex items-baseline gap-2">
            <span className="text-sm text-slate-500">Total Tests</span>
            <span className="text-2xl font-bold text-slate-900">
              {summary.totalTests}
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-sm text-slate-500">Pass Rate</span>
            <span className="text-2xl font-bold text-emerald-600">
              {summary.passRate}%
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-sm text-slate-500">Avg Duration</span>
            <span className="text-2xl font-bold text-blue-600">
              {summary.avgDuration}s
            </span>
          </div>
        </div>
      </div>

      {/* Timeline Table */}
      <div className="flex-1 overflow-y-auto">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 bg-white border-b border-slate-200">
            <tr>
              <th className="px-6 py-3 text-left font-semibold text-slate-700">
                Status
              </th>
              <th className="px-6 py-3 text-left font-semibold text-slate-700">
                Story ID
              </th>
              <th className="px-6 py-3 text-left font-semibold text-slate-700">
                Test File
              </th>
              <th className="px-6 py-3 text-right font-semibold text-slate-700">
                Duration (s)
              </th>
              <th className="px-6 py-3 text-left font-semibold text-slate-700">
                Timestamp
              </th>
            </tr>
          </thead>
          <tbody className="bg-white">
            {results.map((result: PhaseVResult) => (
              <tr
                key={result.id}
                className="border-b border-slate-100 hover:bg-slate-50 transition-colors"
              >
                <td className="px-6 py-3">
                  <span
                    className={`px-2 py-1 rounded text-xs font-semibold ${
                      result.passed
                        ? 'bg-emerald-100 text-emerald-700'
                        : 'bg-red-100 text-red-700'
                    }`}
                  >
                    {result.passed ? '✓ Passed' : '✗ Failed'}
                  </span>
                </td>
                <td className="px-6 py-3 font-mono text-slate-700">
                  {result.story_id}
                </td>
                <td className="px-6 py-3 text-slate-600 font-mono text-xs">
                  {result.test_file}
                </td>
                <td className="px-6 py-3 text-right text-slate-600 font-mono">
                  {result.duration_s}s
                </td>
                <td className="px-6 py-3 text-slate-500 text-xs">
                  {new Date(result.timestamp).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
