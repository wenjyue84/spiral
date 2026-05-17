import { useState, useEffect, useRef } from 'react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

interface HealthData {
  status: string;
  timestamp: string;
  phases: Record<string, number>;
  workers: {
    active: number;
    crashed: number;
    total: number;
  };
  tokens: {
    current_rate: number;
    average_rate: number;
    trend: number[];
  };
}

export default function HealthWidget() {
  const [data, setData] = useState<HealthData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const retryCountRef = useRef(0);
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const fetchHealth = async () => {
      try {
        abortControllerRef.current = new AbortController();
        const res = await fetch('/api/health', {
          signal: abortControllerRef.current.signal
        });

        if (!res.ok) {
          throw new Error(`Health check failed with status ${res.status}`);
        }

        const json = await res.json() as HealthData;
        setData(json);
        setError(null);
        retryCountRef.current = 0;
      } catch (err) {
        if ((err as Error).name !== 'AbortError') {
          setError(String(err));
        }
      } finally {
        setLoading(false);
      }
    };

    // Initial fetch
    fetchHealth();

    // Set up regular polling every 5 seconds
    const pollInterval = setInterval(fetchHealth, 5000);

    return () => {
      clearInterval(pollInterval);
      abortControllerRef.current?.abort();
    };
  }, []);

  // Convert token trend to chart data
  const trendData = data?.tokens.trend.map((value, index) => ({
    index,
    value
  })) ?? [];

  const highestPhase = data ? (
    Object.entries(data.phases).reduce((a, b) =>
      a[1] > b[1] ? a : b
    )
  ) : null;

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="mb-4">
        <h3 className="text-sm font-semibold text-slate-800">Health Metrics</h3>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
          <div className="text-xs font-medium text-red-700">Connection Error</div>
          <div className="text-xs text-red-600 mt-1">{error}</div>
          <div className="text-xs text-red-500 mt-1">Retrying every 5 seconds…</div>
        </div>
      )}

      {loading && !data && (
        <div className="flex items-center justify-center h-40 text-slate-400 text-sm">
          Loading health metrics…
        </div>
      )}

      {!loading && data && (
        <div className="space-y-4">
          {/* Workers card */}
          <div className="bg-gradient-to-br from-purple-50 to-purple-100 rounded-lg p-4 border border-purple-200">
            <div className="text-xs text-purple-600 font-medium mb-2">Workers</div>
            <div className="flex items-end gap-3">
              <div>
                <div className="text-2xl font-bold text-purple-700">{data.workers.active}</div>
                <div className="text-xs text-purple-600">active</div>
              </div>
              {data.workers.crashed > 0 && (
                <div>
                  <div className="text-lg font-bold text-red-600">{data.workers.crashed}</div>
                  <div className="text-xs text-red-600">crashed</div>
                </div>
              )}
              <div className="ml-auto text-right">
                <div className="text-xs text-purple-600">of {data.workers.total}</div>
              </div>
            </div>
          </div>

          {/* Token burn rate card */}
          <div className="bg-gradient-to-br from-amber-50 to-amber-100 rounded-lg p-4 border border-amber-200">
            <div className="text-xs text-amber-600 font-medium mb-2">Token Burn Rate</div>
            <div className="flex items-center justify-between">
              <div>
                <div className="text-2xl font-bold text-amber-700">
                  {data.tokens.current_rate}
                </div>
                <div className="text-xs text-amber-600">tokens/min</div>
              </div>
              <div className="text-right">
                <div className="text-xs text-amber-600 mb-1">Avg: {data.tokens.average_rate}t/m</div>
                {trendData.length > 0 && (
                  <ResponsiveContainer width={120} height={40}>
                    <AreaChart data={trendData} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
                      <Area type="monotone" dataKey="value" stroke="#b45309" fill="#fcd34d" strokeWidth={1.5} dot={false} />
                    </AreaChart>
                  </ResponsiveContainer>
                )}
              </div>
            </div>
          </div>

          {/* Phase durations card */}
          {highestPhase && (
            <div className="bg-gradient-to-br from-blue-50 to-blue-100 rounded-lg p-4 border border-blue-200">
              <div className="text-xs text-blue-600 font-medium mb-2">Slowest Phase</div>
              <div>
                <div className="text-2xl font-bold text-blue-700">
                  {(highestPhase[1] / 1000).toFixed(1)}s
                </div>
                <div className="text-xs text-blue-600">Phase {highestPhase[0]}</div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
