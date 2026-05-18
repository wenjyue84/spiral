import { useMemo } from 'react';
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import { useCostsBreakdown } from '../hooks/useCostsBreakdown';

export default function CostAnalysisTab() {
  const { data, isLoading, error } = useCostsBreakdown();

  const barChartData = useMemo(() => {
    if (!data?.entries) return [];
    return data.entries.map(entry => ({
      phase: entry.phase,
      cost: entry.cost_usd,
      tokens: entry.token_count,
    }));
  }, [data]);

  const lineChartData = useMemo(() => {
    if (!data?.entries) return [];
    let cumulative = 0;
    return data.entries.map(entry => {
      cumulative += entry.cost_usd;
      return {
        phase: entry.phase,
        cumulative_cost: Math.round(cumulative * 100) / 100,
      };
    });
  }, [data]);

  const budgetProjection = useMemo(() => {
    if (!data) {
      return { spend: 0, burnRate: 0, remaining: 0, percentUsed: 0 };
    }
    const spend = Math.round(data.total_cost_usd * 100) / 100;
    const burnRate = Math.round(data.burn_rate_per_minute * 100) / 100;
    const remaining = Math.max(0, Math.round((data.ceiling_usd - data.total_cost_usd) * 100) / 100);
    const percentUsed = data.ceiling_usd > 0 ? Math.round((data.total_cost_usd / data.ceiling_usd) * 100) : 0;
    return { spend, burnRate, remaining, percentUsed };
  }, [data]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500 text-sm">
        Loading cost analysis…
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 text-sm text-red-500">
        Error loading cost data: {(error as Error).message}
      </div>
    );
  }

  if (!data || data.entries.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400 text-sm flex-col gap-2">
        <span className="text-3xl">💰</span>
        <span>No cost data available yet</span>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col overflow-hidden bg-slate-50">
      {/* Budget Projection Card */}
      <div className="bg-white border-b border-slate-200 px-6 py-4 flex-shrink-0">
        <div className="flex items-center gap-8">
          <div className="flex items-baseline gap-2">
            <span className="text-sm text-slate-500">Spend:</span>
            <span className="text-2xl font-bold text-slate-900">
              ${budgetProjection.spend}
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-sm text-slate-500">Burn rate:</span>
            <span className="text-2xl font-bold text-orange-600">
              ${budgetProjection.burnRate}/min
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-sm text-slate-500">Remaining:</span>
            <span
              className={`text-2xl font-bold ${
                budgetProjection.percentUsed >= 80 ? 'text-red-600' :
                budgetProjection.percentUsed >= 50 ? 'text-amber-600' :
                'text-emerald-600'
              }`}
            >
              ${budgetProjection.remaining}
            </span>
          </div>
          {data.ceiling_usd > 0 && (
            <div className="flex items-baseline gap-2">
              <span className="text-sm text-slate-500">Usage:</span>
              <div className="flex items-center gap-2">
                <div className="w-24 h-2 rounded-full bg-slate-200 overflow-hidden">
                  <div
                    className={`h-full rounded-full ${
                      budgetProjection.percentUsed >= 80 ? 'bg-red-500' :
                      budgetProjection.percentUsed >= 50 ? 'bg-amber-500' :
                      'bg-emerald-500'
                    }`}
                    style={{ width: `${Math.min(budgetProjection.percentUsed, 100)}%` }}
                  />
                </div>
                <span className="text-sm font-medium text-slate-700 w-8 text-right">
                  {budgetProjection.percentUsed}%
                </span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Charts Container */}
      <div className="flex-1 overflow-y-auto grid grid-cols-1 lg:grid-cols-2 gap-6 p-6">
        {/* Stacked Bar Chart */}
        <div className="bg-white rounded-lg border border-slate-200 p-4">
          <h3 className="text-sm font-semibold text-slate-700 mb-4">Cost by Phase</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={barChartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="phase" tick={{ fontSize: 12, fill: '#64748b' }} />
              <YAxis tick={{ fontSize: 12, fill: '#64748b' }} label={{ value: 'Cost (USD)', angle: -90, position: 'insideLeft' }} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #475569', borderRadius: '4px' }}
                labelStyle={{ color: '#e2e8f0' }}
                formatter={(value: number) => `$${value.toFixed(2)}`}
              />
              <Legend />
              <Bar dataKey="cost" fill="#3b82f6" name="Cost (USD)" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Cumulative Line Chart */}
        <div className="bg-white rounded-lg border border-slate-200 p-4">
          <h3 className="text-sm font-semibold text-slate-700 mb-4">Cumulative Spend</h3>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={lineChartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="phase" tick={{ fontSize: 12, fill: '#64748b' }} />
              <YAxis tick={{ fontSize: 12, fill: '#64748b' }} label={{ value: 'Cumulative (USD)', angle: -90, position: 'insideLeft' }} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #475569', borderRadius: '4px' }}
                labelStyle={{ color: '#e2e8f0' }}
                formatter={(value: number) => `$${value.toFixed(2)}`}
              />
              <Line
                type="monotone"
                dataKey="cumulative_cost"
                stroke="#10b981"
                strokeWidth={2}
                name="Cumulative Spend (USD)"
                dot={{ fill: '#10b981', r: 4 }}
                activeDot={{ r: 6 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
