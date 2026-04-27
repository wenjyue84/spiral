import { useState, useEffect } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

interface ThroughputData {
  velocity: number; // stories per hour
  cycleTimeByComplexity: Array<{
    complexity: string;
    medianCycleTimeMinutes: number;
  }>;
}

export default function ThroughputMetrics({ isRunning }: { isRunning: boolean }) {
  const [data, setData] = useState<ThroughputData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Fetch immediately on mount
    const fetchThroughput = async () => {
      try {
        const res = await fetch('/api/throughput');
        if (!res.ok) throw new Error('Failed to fetch throughput data');
        const json = await res.json() as ThroughputData;
        setData(json);
        setError(null);
      } catch (err) {
        setError(String(err));
        setData(null);
      } finally {
        setLoading(false);
      }
    };

    fetchThroughput();

    // Only set up polling if iteration is running
    if (!isRunning) return;

    const interval = setInterval(fetchThroughput, 30_000); // 30 seconds
    return () => clearInterval(interval);
  }, [isRunning]);

  // Check if we have insufficient data
  const hasInsufficientData = !data || !data.cycleTimeByComplexity || data.cycleTimeByComplexity.length === 0;

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="mb-4">
        <h3 className="text-sm font-semibold text-slate-800">Throughput Metrics</h3>
        {!isRunning && <p className="text-xs text-slate-400 mt-1">Auto-refresh paused (iteration idle)</p>}
      </div>

      {loading && (
        <div className="flex items-center justify-center h-40 text-slate-400 text-sm">
          Loading metrics…
        </div>
      )}

      {error && !loading && (
        <div className="flex items-center justify-center h-40 text-red-500 text-sm">
          Error loading metrics
        </div>
      )}

      {!loading && hasInsufficientData && (
        <div className="flex items-center justify-center h-40 text-slate-400 text-sm">
          Insufficient data
        </div>
      )}

      {!loading && !hasInsufficientData && data && (
        <div className="space-y-4">
          {/* Velocity card */}
          <div className="bg-gradient-to-br from-blue-50 to-blue-100 rounded-lg p-4 border border-blue-200">
            <div className="text-xs text-blue-600 font-medium mb-1">Velocity</div>
            <div className="text-2xl font-bold text-blue-700">
              {data.velocity.toFixed(1)}
              <span className="text-sm ml-1">stories/hour</span>
            </div>
          </div>

          {/* Cycle time chart */}
          <div>
            <div className="text-xs text-slate-600 font-medium mb-2">Median Cycle Time by Complexity</div>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={data.cycleTimeByComplexity}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="complexity" stroke="#94a3b8" style={{ fontSize: '12px' }} />
                <YAxis stroke="#94a3b8" style={{ fontSize: '12px' }} label={{ value: 'Minutes', angle: -90, position: 'insideLeft' }} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '6px' }}
                  labelStyle={{ color: '#1e293b' }}
                />
                <Bar dataKey="medianCycleTimeMinutes" fill="#06b6d4" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}
