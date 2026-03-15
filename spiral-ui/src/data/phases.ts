export type PhaseZone = 'startup' | 'pipeline' | 'implement' | 'validate' | 'decision' | 'terminal';

export interface Phase {
  id: string;
  label: string;
  subtitle: string;
  zone: PhaseZone;
  inputs: string[];
  outputs: string[];
  skipCondition?: string;
  script?: string;
  x: number;
  y: number;
}

export interface DataFile {
  id: string;
  label: string;
  x: number;
  y: number;
}

export const PHASES: Phase[] = [
  // ── Startup ────────────────────────────────────────────────────────────────
  {
    id: '0a', label: '0-A Constitution', subtitle: 'Create / review rules',
    zone: 'startup', script: 'lib/phases/phase_0_clarify.sh',
    inputs: [], outputs: ['constitution.md'],
    x: 60, y: 40,
  },
  {
    id: '0b', label: '0-B Focus', subtitle: 'Set session theme',
    zone: 'startup', script: 'lib/phases/phase_0_clarify.sh',
    inputs: [], outputs: ['SPIRAL_FOCUS'],
    x: 60, y: 120,
  },
  {
    id: '0c', label: '0-C Clarify', subtitle: '3 questions to lock scope',
    zone: 'startup', script: 'lib/phases/phase_0_clarify.sh',
    inputs: [], outputs: [],
    x: 60, y: 200,
  },
  {
    id: '0d', label: '0-D Story Prep', subtitle: 'Seed (→ prd.json) or AI pick (→ queue)',
    zone: 'startup', script: 'lib/phases/phase_0_clarify.sh',
    inputs: [], outputs: ['prd.json (seeds)', '_ai_example_queue.json'],
    x: 60, y: 280,
  },
  {
    id: '0e', label: '0-E Options', subtitle: 'Time limit · gate mode',
    zone: 'startup', script: 'lib/phases/phase_0_clarify.sh',
    inputs: [], outputs: ['TIME_LIMIT_MINS'],
    x: 60, y: 360,
  },

  // ── Loop ───────────────────────────────────────────────────────────────────
  {
    id: 'A', label: 'Phase A', subtitle: 'AI Suggestions (Sources 2 & 5)',
    zone: 'pipeline', script: 'lib/ai_suggest.py + lib/generate_test_stories.py',
    inputs: ['prd.json', '_ai_example_queue.json'],
    outputs: ['_ai_suggest_output.json', '_test_story_candidates.json'],
    x: 400, y: 100,
  },
  {
    id: 'R', label: 'Phase R', subtitle: 'Research — Claude agent (parallel with T)',
    zone: 'pipeline', script: 'Claude agent + Gemini',
    inputs: ['SPIRAL_RESEARCH_PROMPT', 'prd.json'],
    outputs: ['_research_output.json'],
    skipCondition: '--skip-research, over-capacity, cache hit',
    x: 300, y: 220,
  },
  {
    id: 'T', label: 'Phase T', subtitle: 'Test Synthesis (parallel with R)',
    zone: 'pipeline', script: 'lib/synthesize_tests.py',
    inputs: ['test-reports/'],
    outputs: ['_test_stories_output.json'],
    skipCondition: 'memory pressure',
    x: 510, y: 220,
  },
  {
    id: 'S', label: 'Phase S', subtitle: 'Story Validate',
    zone: 'pipeline', script: 'lib/validate_stories.py',
    inputs: ['_research_output.json', '_test_stories_output.json', '_ai_suggest_output.json', '_test_story_candidates.json'],
    outputs: ['_validated_stories.json', '_story_rejected.json'],
    x: 400, y: 340,
  },
  {
    id: 'M', label: 'Phase M', subtitle: 'Merge → prd.json',
    zone: 'pipeline', script: 'lib/merge_stories.py',
    inputs: ['_validated_stories.json', '_research_overflow.json'],
    outputs: ['prd.json (patched)', '_research_overflow.json'],
    x: 400, y: 460,
  },
  {
    id: 'G', label: 'Phase G', subtitle: 'Gate (human checkpoint)',
    zone: 'decision',
    inputs: [], outputs: [],
    skipCondition: '--gate proceed',
    x: 400, y: 560,
  },
  {
    id: 'I', label: 'Phase I', subtitle: 'Implement — Ralph inner loop',
    zone: 'implement', script: 'ralph/ralph.sh',
    inputs: ['prd.json'],
    outputs: ['prd.json (passes:true)', 'results.tsv'],
    x: 400, y: 660,
  },
  {
    id: 'V', label: 'Phase V', subtitle: 'Validate — tests + persistent suites',
    zone: 'validate', script: 'lib/test_suite_manager.py + SPIRAL_VALIDATE_CMD',
    inputs: ['test-reports/', 'prd.json'],
    outputs: ['test-reports/', '.spiral/test-suites/'],
    x: 400, y: 760,
  },
  {
    id: 'C', label: 'Phase C', subtitle: 'Check Done',
    zone: 'decision', script: 'lib/check_done.py',
    inputs: ['prd.json', 'test-reports/'],
    outputs: [],
    x: 400, y: 860,
  },
  {
    id: 'D', label: 'Phase D', subtitle: 'AI Suggestions — always loops back to Phase A',
    zone: 'decision',
    inputs: ['prd.json (after iter)'],
    outputs: [],
    skipCondition: 'Never exits here — SPIRAL only ends via max iters / time limit / cost ceiling',
    x: 400, y: 960,
  },
];

export const ZONE_COLORS: Record<PhaseZone, { bg: string; border: string; text: string; badge: string }> = {
  startup:  { bg: '#dcfce7', border: '#16a34a', text: '#14532d', badge: 'bg-green-600' },
  pipeline: { bg: '#dbeafe', border: '#2563eb', text: '#1e3a8a', badge: 'bg-blue-600' },
  implement:{ bg: '#fed7aa', border: '#ea580c', text: '#7c2d12', badge: 'bg-orange-600' },
  validate: { bg: '#ede9fe', border: '#7c3aed', text: '#3b0764', badge: 'bg-violet-600' },
  decision: { bg: '#fef9c3', border: '#ca8a04', text: '#713f12', badge: 'bg-yellow-600' },
  terminal: { bg: '#d1fae5', border: '#059669', text: '#064e3b', badge: 'bg-emerald-600' },
};
