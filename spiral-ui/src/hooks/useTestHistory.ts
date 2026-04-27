import { useQuery } from '@tanstack/react-query';

export interface TestHistoryEntry {
  id: string;
  date: string;
  testFile: string;
  status: 'passed' | 'failed' | 'error';
  coverage: number;
  output?: string;
}

export interface TestHistoryResponse {
  entries: TestHistoryEntry[];
}

export function useTestHistory(daysBack?: number) {
  return useQuery<TestHistoryResponse>({
    queryKey: ['testHistory', daysBack],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (daysBack) params.append('days', String(daysBack));
      const res = await fetch(`/api/tests/history?${params}`);
      if (!res.ok) throw new Error(`Failed to fetch test history: ${res.statusText}`);
      return res.json();
    },
    staleTime: 30_000, // 30s
    refetchInterval: 60_000, // 60s
  });
}
