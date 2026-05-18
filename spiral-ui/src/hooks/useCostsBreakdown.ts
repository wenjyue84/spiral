import { useState, useEffect } from 'react';

export interface CostBreakdownEntry {
  phase: string;
  cost_usd: number;
  token_count: number;
}

export interface CostBreakdownData {
  entries: CostBreakdownEntry[];
  total_cost_usd: number;
  burn_rate_per_minute: number;
  ceiling_usd: number;
}

export function useCostsBreakdown() {
  const [data, setData] = useState<CostBreakdownData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = async () => {
    try {
      setIsLoading(true);
      const res = await fetch('/api/costs/breakdown');
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const json = await res.json() as CostBreakdownData;
      setData(json);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  return { data, isLoading, error };
}
