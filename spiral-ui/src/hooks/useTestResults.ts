import { useState, useEffect } from 'react';

export interface TestSummary {
  story_id: string;
  test_status?: string;
  test_count: number;
  file_touch_ok: boolean;
  coverage_pct: number;
}

export function useTestResults() {
  const [data, setData] = useState<TestSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchTestResults = async () => {
      try {
        setLoading(true);
        setError(null);
        const response = await fetch('/api/tests/summary');
        if (!response.ok) {
          throw new Error(`Failed to fetch test results: ${response.statusText}`);
        }
        const results = (await response.json()) as TestSummary[];
        setData(results);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    void fetchTestResults();
  }, []);

  return { data, loading, error };
}
