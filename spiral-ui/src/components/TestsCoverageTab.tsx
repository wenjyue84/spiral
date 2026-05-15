import { useState, useMemo } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, Cell } from 'recharts';

interface CoverageFile {
  path: string;
  coverage_percent: number;
  status: string;
  covered_lines: number;
  uncovered_lines: number;
}

interface CoverageSummary {
  total_files: number;
  covered_files: number;
  avg_coverage: number;
  overall_status: string;
}

interface CoverageData {
  files: CoverageFile[];
  summary: CoverageSummary;
}

const statusColorMap: Record<string, string> = {
  red: '#ef4444',
  yellow: '#eab308',
  green: '#22c55e',
};

const statusBgMap: Record<string, string> = {
  red: 'bg-red-50 border-red-200',
  yellow: 'bg-yellow-50 border-yellow-200',
  green: 'bg-green-50 border-green-200',
};

export default function TestsCoverageTab() {
  const [expandedFile, setExpandedFile] = useState<string | null>(null);
  const [data, setData] = useState<CoverageData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch coverage data on mount
  useMemo(() => {
    const fetchCoverage = async () => {
      try {
        const res = await fetch('/api/tests/coverage');
        if (!res.ok) {
          throw new Error('Failed to fetch coverage data');
        }
        const coverageData = await res.json() as CoverageData;
        setData(coverageData);
        setError(null);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setIsLoading(false);
      }
    };

    fetchCoverage();
  }, []);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500 text-sm">
        Loading coverage data…
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 text-sm text-red-500">
        Error loading coverage data: {error}
      </div>
    );
  }

  if (!data || data.files.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400 text-sm flex-col gap-2">
        <span className="text-3xl">📊</span>
        <span>No coverage data available</span>
      </div>
    );
  }

  const { files, summary } = data;

  // Prepare chart data
  const chartData = files
    .slice(0, 20) // Limit to top 20 files for readability
    .map((file) => ({
      path: file.path.split('/').pop() || file.path,
      fullPath: file.path,
      coverage: file.coverage_percent,
      covered: file.covered_lines,
      uncovered: file.uncovered_lines,
    }));

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header with summary stats */}
      <div className="px-6 py-4 border-b border-slate-200 bg-white flex-shrink-0">
        <h2 className="text-sm font-semibold text-slate-800 mb-3">Coverage Summary</h2>
        <div className="grid grid-cols-4 gap-4">
          <div className={`p-3 rounded-lg border ${statusBgMap[summary.overall_status]}`}>
            <div className="text-xs text-slate-600 font-medium">Overall Status</div>
            <div className="text-lg font-bold" style={{ color: statusColorMap[summary.overall_status] }}>
              {summary.overall_status === 'red' ? '🔴' : summary.overall_status === 'yellow' ? '🟡' : '🟢'}
            </div>
          </div>
          <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
            <div className="text-xs text-slate-600 font-medium">Avg Coverage</div>
            <div className="text-lg font-bold text-slate-800">{summary.avg_coverage.toFixed(1)}%</div>
          </div>
          <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
            <div className="text-xs text-slate-600 font-medium">Files Covered</div>
            <div className="text-lg font-bold text-slate-800">
              {summary.covered_files}/{summary.total_files}
            </div>
          </div>
          <div className="p-3 rounded-lg border border-slate-200 bg-slate-50">
            <div className="text-xs text-slate-600 font-medium">Total Files</div>
            <div className="text-lg font-bold text-slate-800">{summary.total_files}</div>
          </div>
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 overflow-hidden flex flex-col gap-4 px-6 py-4">
        {/* Chart */}
        <div className="bg-white rounded-lg border border-slate-200 p-4 flex-shrink-0">
          <h3 className="text-sm font-semibold text-slate-800 mb-3">File Coverage Distribution (Top 20)</h3>
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} layout="vertical" margin={{ top: 5, right: 30, left: 200, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 12 }} />
                <YAxis dataKey="path" type="category" width={195} tick={{ fontSize: 11 }} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#1e293b', border: 'none', borderRadius: '6px' }}
                  labelStyle={{ color: '#e2e8f0' }}
                  formatter={(value: number) => `${value}%`}
                  cursor={{ fill: 'rgba(59, 130, 246, 0.1)' }}
                />
                <Bar dataKey="coverage" radius={[0, 4, 4, 0]}>
                  {chartData.map((entry, index) => {
                    const file = files.find((f) => f.path.endsWith(entry.path));
                    const color = file ? statusColorMap[file.status] : '#94a3b8';
                    return <Cell key={`cell-${index}`} fill={color} />;
                  })}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Files table */}
        <div className="flex-1 overflow-hidden flex flex-col bg-white rounded-lg border border-slate-200">
          <div className="overflow-y-auto flex-1">
            <table className="w-full border-collapse text-sm">
              <thead className="sticky top-0 bg-slate-50 border-b border-slate-200">
                <tr>
                  <th className="px-4 py-3 text-left font-semibold text-slate-700 w-1/2">File Path</th>
                  <th className="px-4 py-3 text-center font-semibold text-slate-700">Coverage %</th>
                  <th className="px-4 py-3 text-center font-semibold text-slate-700">Status</th>
                  <th className="px-4 py-3 text-right font-semibold text-slate-700">Covered/Uncovered</th>
                  <th className="px-4 py-3 w-8" />
                </tr>
              </thead>
              <tbody>
                {files.map((file) => (
                  <tbody key={file.path}>
                    <tr className="border-b border-slate-100 hover:bg-slate-50 transition-colors">
                      <td className="px-4 py-3 text-slate-700 font-mono text-xs break-words">{file.path}</td>
                      <td className="px-4 py-3 text-center text-slate-600 font-mono font-semibold">
                        {file.coverage_percent.toFixed(1)}%
                      </td>
                      <td className="px-4 py-3 text-center">
                        <span
                          className={`inline-block w-3 h-3 rounded-full`}
                          style={{ backgroundColor: statusColorMap[file.status] }}
                          title={file.status}
                        />
                      </td>
                      <td className="px-4 py-3 text-right text-slate-600 font-mono text-xs">
                        {file.covered_lines}/{file.covered_lines + file.uncovered_lines}
                      </td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => setExpandedFile(expandedFile === file.path ? null : file.path)}
                          className="text-slate-400 hover:text-slate-700 transition-colors"
                        >
                          {expandedFile === file.path ? '▾' : '▸'}
                        </button>
                      </td>
                    </tr>
                    {expandedFile === file.path && (
                      <tr className="border-b border-slate-200 bg-slate-50">
                        <td colSpan={5} className="px-4 py-3">
                          <div className="grid grid-cols-2 gap-4 text-sm">
                            <div>
                              <div className="text-slate-600 font-medium mb-1">File Details</div>
                              <div className="text-xs text-slate-600 space-y-1">
                                <div>
                                  <span className="font-semibold">Coverage:</span> {file.coverage_percent.toFixed(1)}%
                                </div>
                                <div>
                                  <span className="font-semibold">Covered Lines:</span> {file.covered_lines}
                                </div>
                                <div>
                                  <span className="font-semibold">Uncovered Lines:</span> {file.uncovered_lines}
                                </div>
                                <div>
                                  <span className="font-semibold">Total Lines:</span>{' '}
                                  {file.covered_lines + file.uncovered_lines}
                                </div>
                              </div>
                            </div>
                            <div>
                              <div className="text-slate-600 font-medium mb-1">Status Breakdown</div>
                              <div className="text-xs text-slate-600">
                                {file.status === 'green' && (
                                  <div className="text-green-700 font-semibold">✓ Well covered (&gt;80%)</div>
                                )}
                                {file.status === 'yellow' && (
                                  <div className="text-yellow-700 font-semibold">⚠ Partially covered (50-80%)</div>
                                )}
                                {file.status === 'red' && (
                                  <div className="text-red-700 font-semibold">✗ Poorly covered (&lt;50%)</div>
                                )}
                              </div>
                            </div>
                          </div>
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
