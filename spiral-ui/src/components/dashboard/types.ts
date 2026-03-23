import type { StoryAttempt } from '../StoryDetailPanel';

// ── Types ────────────────────────────────────────────────────────────────────

export interface Story {
  id: string;
  title: string;
  description?: string;
  passes: boolean;
  priority?: string;
  complexity?: string;
  failureReason?: string;
  dependencies?: string[];
  status?: string;
  source?: string;
  retryCount?: number;
  acceptanceCriteria?: string[];
  filesTouch?: string[];
  completedAt?: string | null;
  scopeCreep?: boolean;
  lastAttempted?: string | null;
}

export interface ProgressData {
  total: number;
  done: number;
  pending: number;
  productName?: string;
  overview?: string;
  stories: Story[];
}

export interface ProgressSnapshot {
  ts: string;
  iter: number;
  done: number;
  pending: number;
  total: number;
  added: number;
}

export interface TokenBurnEntry {
  story_id: string;
  input: number;
  output: number;
  total: number;
  calls: number;
}

export interface CachePhaseEntry {
  phase: string;
  hit_rate: number;
  hits: number;
  total: number;
  creation_tokens: number;
  read_tokens: number;
}

export interface LastCompletedStory {
  id: string;
  title: string;
  timestamp: string;
  model?: string;
  duration?: number;
}

export interface ActiveStatus {
  phase: string;
  iteration: number;
  started_at: number;
  pct_done: number;
  story_id?: string;
  story_title?: string;
}

export interface ActiveStoryInfo {
  storyId: string | null;
  title: string | null;
}

export interface ProjectData {
  name: string;
  root: string;
  lastSeen: string;
  progress: ProgressData | null;
  config: Record<string, string>;
  configRaw: string;
  constitution: string;
  activity: string;
  progressHistory: ProgressSnapshot[];
  tokenBurn?: TokenBurnEntry[];
  cacheStats?: CachePhaseEntry[];
  lastCompletedStory?: LastCompletedStory | null;
  recentlyCompleted?: LastCompletedStory[];
  checkpointTs?: string | null;
  lastLogModified?: string | null;
  activeStatus?: ActiveStatus | null;
  storyAttempts?: Record<string, StoryAttempt[]>;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

export function pct(done: number, total: number) {
  return total > 0 ? Math.round((done / total) * 100) : 0;
}
