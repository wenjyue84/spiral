import { useState, useMemo } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { useTestHistory, type TestHistoryEntry } from '../hooks/useTestHistory';

type DateRangeFilter = '7d' | '30d' | 'all';

interface ChartDataPoint {
  date: string;
  passRate: number;
}

export default function TestsTab() {
  const [dateRange, setDateRange] = useState<DateRangeFilter>('30d');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Determine days back from filter
  const daysBack = dateRange === '7d' ? 7 : dateRange === '30d' ? 30 : undefined;
  const { data, isLoading, error } = useTestHistory(daysBack);

  // Filter and compute stats
  const entries = useMemo(() => {
    if (!data?.entries) return [];
    return data.entries.sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
  }, [data]);

  // Compute trend data for chart
  const trendData = useMemo(() => {
    if (entries.length === 0) return [];
    // Group by date and compute pass rate
    const byDate: Record<string, { passed: number; total: number }> = {};
    entries.forEach(e => {
      if (!byDate[e.date]) byDate[e.date] = { passed: 0, total: 0 };
      byDate[e.date].total += 1;
      if (e.status === 'passed') byDate[e.date].passed += 1;
    });
    // Convert to chart format, sorted by date
    const data = Object.entries(byDate)
      .map(([date, { passed, total }]) => ({
        date,
        passRate: Math.round((passed / total) * 100),
      }))
      .sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());
    return data;
  }, [entries]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500 text-sm">
        Loading test history…
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 text-sm text-red-500">
        Error loading test history: {(error as Error).message}
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400 text-sm flex-col gap-2">
        <span className="text-3xl">📊</span>
        <span>No test history yet</span>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Controls */}
      <div className="px-6 py-4 border-b border-slate-200 bg-white flex-shrink-0 flex items-center gap-4">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-slate-600">Date range:</span>
          <div className="flex gap-2">
            {(['7d', '30d', 'all'] as const).map(range => (
              <button
                key={range}
                onClick={() => setDateRange(range)}
                className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                  dateRange === range
                    ? 'bg-blue-600 text-white'
                    : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                }`}
              >
                {range === '7d' ? 'Last 7 days' : range === '30d' ? 'Last 30 days' : 'All'}
              </button>
            ))}
          </div>
        </div>
        <div className="ml-auto text-xs text-slate-500">
          {entries.length} test result{entries.length !== 1 ? 's' : ''}
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 overflow-hidden flex flex-col gap-4 px-6 py-4">
        {/* Chart */}
        {trendData.length > 0 && (
          <div className="bg-white rounded-lg border border-slate-200 p-4 flex-shrink-0">
            <h3 className="text-sm font-semibold text-slate-800 mb-3">Pass Rate Trend</h3>
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={trendData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 12 }}
                    tickFormatter={(date: string) => new Date(date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                  />
                  <YAxis
                    domain={[0, 100]}
                    tick={{ fontSize: 12 }}
                    label={{ value: 'Pass Rate (%)', angle: -90, position: 'insideLeft' }}
                  />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#1e293b', border: 'none', borderRadius: '6px' }}
                    labelStyle={{ color: '#e2e8f0' }}
                    formatter={(value: number) => `${value}%`}
                  />
                  <Line
                    type="monotone"
                    dataKey="passRate"
                    stroke="#3b82f6"
                    strokeWidth={2}
                    dot={{ fill: '#3b82f6', r: 4 }}
                    connectNulls
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}

        {/* Table */}
        <div className="flex-1 overflow-hidden flex flex-col bg-white rounded-lg border border-slate-200">
          <div className="overflow-y-auto flex-1">
            <table className="w-full border-collapse text-sm">
              <thead className="sticky top-0 bg-slate-50 border-b border-slate-200">
                <tr>
                  <th className="px-4 py-3 text-left font-semibold text-slate-700">Date</th>
                  <th className="px-4 py-3 text-left font-semibold text-slate-700">Test File</th>
                  <th className="px-4 py-3 text-left font-semibold text-slate-700">Status</th>
                  <th className="px-4 py-3 text-right font-semibold text-slate-700">Coverage %</th>
                  <th className="px-4 py-3 w-8" />
                </tr>
              </thead>
              <tbody>
                {entries.map(entry => (
                  <tbody key={entry.id}>
                    <tr className="border-b border-slate-100 hover:bg-slate-50 transition-colors">
                      <td className="px-4 py-3 text-slate-700 font-mono text-xs">
                        {new Date(entry.date).toLocaleString()}
                      </td>
                      <td className="px-4 py-3 text-slate-600 font-mono text-xs">{entry.testFile}</td>
                      <td className="px-4 py-3">
                        <span
                          className={`px-2 py-1 rounded text-xs font-semibold ${
                            entry.status === 'passed'
                              ? 'bg-emerald-100 text-emerald-700'
                              : entry.status === 'failed'
                              ? 'bg-red-100 text-red-700'
                              : 'bg-orange-100 text-orange-700'
                          }`}
                        >
                          {entry.status === 'passed' ? '✓ Passed' : entry.status === 'failed' ? '✗ Failed' : '! Error'}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right text-slate-600 font-mono">{entry.coverage}%</td>
                      <td className="px-4 py-3">
                        {entry.output && (
                          <button
                            onClick={() => setExpandedId(expandedId === entry.id ? null : entry.id)}
                            className="text-slate-400 hover:text-slate-700 transition-colors"
                          >
                            {expandedId === entry.id ? '▾' : '▸'}
                          </button>
                        )}
                      </td>
                    </tr>
                    {expandedId === entry.id && entry.output && (
                      <tr className="border-b border-slate-200 bg-slate-50">
                        <td colSpan={5} className="px-4 py-3">
                          <pre className="bg-slate-900 text-slate-100 p-3 rounded text-xs overflow-x-auto font-mono max-h-64 overflow-y-auto whitespace-pre-wrap break-words">
                            {entry.output}
                          </pre>
                        </td>
                      </tr>
                    )}
                  </tbody>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
