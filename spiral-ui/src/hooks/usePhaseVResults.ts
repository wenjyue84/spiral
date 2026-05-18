import { useState, useEffect } from 'react';
import type { PhaseVResult } from '../types/phase';

export function usePhaseVResults() {
  const [data, setData] = useState<PhaseVResult[] | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setIsLoading(true);
        setError(null);
        const response = await fetch('/api/phase-v-results');
        if (!response.ok) {
          throw new Error(`Failed to fetch phase V results: ${response.statusText}`);
        }
        const results = (await response.json()) as PhaseVResult[];
        setData(results);
      } catch (err) {
        setError(err instanceof Error ? err : new Error(String(err)));
      } finally {
        setIsLoading(false);
      }
    };

    void fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  return { data, isLoading, error };
}
