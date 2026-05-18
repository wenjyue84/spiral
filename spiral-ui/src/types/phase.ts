export interface PhaseVResult {
  id: string;
  story_id: string;
  test_file: string;
  duration_s: number;
  passed: boolean;
  timestamp: string;
}
