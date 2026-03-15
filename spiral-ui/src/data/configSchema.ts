export interface ConfigField {
  key: string;
  label: string;
  description: string;
  type: 'text' | 'number' | 'select' | 'toggle';
  defaultValue: string | number | boolean;
  options?: { label: string; value: string }[];
  category: string;
  phase?: string;
  placeholder?: string;
}

export const CONFIG_FIELDS: ConfigField[] = [
  // ── Session ─────────────────────────────────────────────────────────────────
  {
    key: 'MAX_SPIRAL_ITERS',
    label: 'Max Spiral Iterations',
    description: 'Maximum outer SPIRAL iterations to run (each is a full R→T→S→M→G→I→V→C cycle). 0 = unlimited.',
    type: 'number', defaultValue: 20, category: 'Session',
    placeholder: '20',
  },
  {
    key: 'TIME_LIMIT_MINS',
    label: 'Time Limit (minutes)',
    description: 'Stop the SPIRAL loop after this many minutes. 0 = unlimited.',
    type: 'number', defaultValue: 0, category: 'Session',
    placeholder: '0 (unlimited)',
  },
  {
    key: 'SPIRAL_GATE_MODE',
    label: 'Gate Mode',
    description: 'Controls Phase G behavior. "interactive" pauses for human review before Phase I.',
    type: 'select', defaultValue: 'interactive', category: 'Session', phase: 'G',
    options: [
      { label: 'Interactive (default)', value: 'interactive' },
      { label: 'Auto-proceed (--gate proceed)', value: 'proceed' },
      { label: 'Skip Phase I (--gate skip)', value: 'skip' },
    ],
  },
  {
    key: 'SPIRAL_FOCUS',
    label: 'Focus Theme',
    description: 'Scope this session to a topic. Phase R only discovers matching stories. Phase M hard-filters research; soft-prioritises test stories.',
    type: 'text', defaultValue: '', category: 'Session',
    placeholder: 'e.g. performance, security, accessibility',
  },

  // ── Story Pipeline ───────────────────────────────────────────────────────────
  {
    key: 'SPIRAL_MAX_PENDING',
    label: 'Max Pending Stories',
    description: 'Phase M stops adding new stories once this many are pending. 0 = unlimited.',
    type: 'number', defaultValue: 0, category: 'Story Pipeline', phase: 'M',
    placeholder: '0 (unlimited)',
  },
  {
    key: 'SPIRAL_MAX_RESEARCH_STORIES',
    label: 'Max Research Stories Per Iteration',
    description: 'Cap how many new stories Phase R can inject per iteration (before dedup). 0 = unlimited.',
    type: 'number', defaultValue: 0, category: 'Story Pipeline', phase: 'R',
    placeholder: '0 (unlimited)',
  },
  {
    key: 'SPIRAL_MAX_AI_SUGGEST',
    label: 'Max AI Suggestions Per Iteration',
    description: 'Phase A gap-analysis stories per iteration (ai-example, Source 2). 0 = disabled.',
    type: 'number', defaultValue: 5, category: 'Story Pipeline', phase: 'A',
    placeholder: '5',
  },
  {
    key: 'SPIRAL_TEST_STORY_MIN_COMPLEXITY',
    label: 'Test Story Min Complexity',
    description: 'Source 5: minimum story complexity to generate test stories from passed stories.',
    type: 'select', defaultValue: 'medium', category: 'Story Pipeline', phase: 'A',
    options: [
      { label: 'Small', value: 'small' },
      { label: 'Medium (default)', value: 'medium' },
      { label: 'Large only', value: 'large' },
    ],
  },
  {
    key: 'SPIRAL_STORY_VALIDATE_MIN_OVERLAP',
    label: 'Story Validate Min Overlap',
    description: 'Phase S: minimum goal-keyword overlap to accept a research or ai-example story. 0 = accept all.',
    type: 'number', defaultValue: 1, category: 'Story Pipeline', phase: 'S',
    placeholder: '1',
  },
  {
    key: 'SPIRAL_STORY_PREFIX',
    label: 'Story ID Prefix',
    description: 'Prefix for story IDs in prd.json (e.g., US → US-001, US-002).',
    type: 'text', defaultValue: 'US', category: 'Story Pipeline',
    placeholder: 'US',
  },

  // ── Research ─────────────────────────────────────────────────────────────────
  {
    key: 'SPIRAL_RESEARCH_MODEL',
    label: 'Research Model',
    description: 'Claude model for Phase R web research agent.',
    type: 'select', defaultValue: 'sonnet', category: 'Research', phase: 'R',
    options: [
      { label: 'Claude Haiku (fastest, cheapest)', value: 'haiku' },
      { label: 'Claude Sonnet (default)', value: 'sonnet' },
      { label: 'Claude Opus (most capable)', value: 'opus' },
    ],
  },
  {
    key: 'SPIRAL_RESEARCH_CACHE_TTL_HOURS',
    label: 'Research Cache TTL (hours)',
    description: 'Cache Phase R URL responses. 0 = disabled. Recommended: 24.',
    type: 'number', defaultValue: 0, category: 'Research', phase: 'R',
    placeholder: '0 (disabled)',
  },
  {
    key: 'SPIRAL_RESEARCH_TIMEOUT',
    label: 'Research Timeout (seconds)',
    description: 'Wall-clock limit for Phase R Claude research call. 0 = unlimited.',
    type: 'number', defaultValue: 300, category: 'Research', phase: 'R',
    placeholder: '300',
  },
  {
    key: 'SPIRAL_CAPACITY_LIMIT',
    label: 'Capacity Limit (pending stories)',
    description: 'Skip Phase R (web research) when pending stories exceed this count.',
    type: 'number', defaultValue: 50, category: 'Research', phase: 'R',
    placeholder: '50',
  },

  // ── Implementation ───────────────────────────────────────────────────────────
  {
    key: 'SPIRAL_MODEL_ROUTING',
    label: 'Model Routing',
    description: 'Controls which Claude model Ralph uses per story.',
    type: 'select', defaultValue: 'auto', category: 'Implementation', phase: 'I',
    options: [
      { label: 'Auto (classify per story)', value: 'auto' },
      { label: 'Haiku (fastest, cheapest)', value: 'haiku' },
      { label: 'Sonnet (balanced)', value: 'sonnet' },
      { label: 'Opus (most capable)', value: 'opus' },
    ],
  },
  {
    key: 'SPIRAL_RALPH_WORKERS',
    label: 'Parallel Workers',
    description: 'Number of parallel Ralph workers. >1 enables git worktree parallel mode.',
    type: 'number', defaultValue: 1, category: 'Implementation', phase: 'I',
    placeholder: '1',
  },
  {
    key: 'SPIRAL_RALPH_ITERS',
    label: 'Max Ralph Inner Iterations',
    description: 'Max turns Ralph gets per implementation phase. Higher = more thorough but slower. Default: 120.',
    type: 'number', defaultValue: 120, category: 'Implementation', phase: 'I',
    placeholder: '120',
  },
  {
    key: 'SPIRAL_IMPL_TIMEOUT',
    label: 'Implementation Timeout (seconds)',
    description: 'Wall-clock limit per ralph call. 0 = unlimited.',
    type: 'number', defaultValue: 600, category: 'Implementation', phase: 'I',
    placeholder: '600',
  },
  {
    key: 'SPIRAL_BRANCH_PREFIX',
    label: 'Feature Branch Prefix',
    description: 'Ralph creates a dedicated git branch per story. Empty = no branching.',
    type: 'text', defaultValue: '', category: 'Implementation', phase: 'I',
    placeholder: 'e.g. spiral',
  },
  {
    key: 'SPIRAL_STORY_TIME_BUDGET',
    label: 'Story Time Budget (seconds)',
    description: 'Max wall-clock seconds per story attempt. 0 = disabled.',
    type: 'number', defaultValue: 0, category: 'Implementation', phase: 'I',
    placeholder: '0 (disabled)',
  },

  // ── Validation ───────────────────────────────────────────────────────────────
  {
    key: 'SPIRAL_VALIDATE_CMD',
    label: 'Validate Command',
    description: 'Integration test command run in Phase V after each Phase I batch.',
    type: 'text', defaultValue: '', category: 'Validation', phase: 'V',
    placeholder: 'e.g. pytest --tb=short  |  npm test  |  bun test',
  },
  {
    key: 'SPIRAL_VALIDATE_TIMEOUT',
    label: 'Validate Timeout (seconds)',
    description: 'Wall-clock limit for the test suite in Phase V. 0 = unlimited.',
    type: 'number', defaultValue: 300, category: 'Validation', phase: 'V',
    placeholder: '300',
  },

  // ── Memory ───────────────────────────────────────────────────────────────────
  {
    key: 'SPIRAL_MEMORY_LIMIT',
    label: 'V8 Heap Cap (MB)',
    description: 'Max Node.js V8 heap per process. Prevents OOM kills. Typical: 1024 (16 GB), 2048 (32 GB+).',
    type: 'number', defaultValue: 1024, category: 'Memory',
    placeholder: '1024',
  },
  {
    key: 'SPIRAL_MEMORY_THRESHOLD',
    label: 'Watchdog Kill Threshold (MB RSS)',
    description: 'RSS threshold at which the watchdog kills a Node.js process. Should be ~50% above V8 cap.',
    type: 'number', defaultValue: 1536, category: 'Memory',
    placeholder: '1536',
  },

  // ── Cost ─────────────────────────────────────────────────────────────────────
  {
    key: 'SPIRAL_COST_CEILING',
    label: 'Cost Ceiling (USD)',
    description: 'SPIRAL stops when total LLM cost exceeds this amount. 0 = unlimited.',
    type: 'number', defaultValue: 0, category: 'Cost',
    placeholder: '0 (unlimited)',
  },
  {
    key: 'SPIRAL_STORY_COST_WARN_USD',
    label: 'Story Cost Warning (USD)',
    description: 'Print a warning when a single story costs more than this. Execution continues.',
    type: 'number', defaultValue: 0.5, category: 'Cost', phase: 'I',
    placeholder: '0.50',
  },
];

export const CATEGORIES = [...new Set(CONFIG_FIELDS.map(f => f.category))];
