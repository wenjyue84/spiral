import { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { type Story, type ActiveStoryInfo } from './ProjectDashboard';
import { formatMYT, timeAgo } from './StoryDetailPanel';

// ── Helpers (used exclusively by PhaseTraceTab) ──────────────────────────────

function stripAnsi(s: string): string {
  return s.replace(/\x1b\[[0-9;]*[mGKHFJ]/g, '').replace(/\u001b\[[0-9;]*[mGKHFJ]/g, '');
}

/**
 * Process a log line for display:
 *   1. Strip ANSI escape codes
 *   2. Convert ISO timestamps → MYT
 *   3. Convert elapsed [M:SS] / [H:MM:SS] → absolute MYT using phaseStart as T=0
 */
function processLogLine(line: string, phaseStart: Date | null = null): string {
  let out = stripAnsi(line);
  // ISO timestamps → MYT
  out = out.replace(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})/g, (match) => {
    try {
      return new Date(match).toLocaleString('en-MY', { timeZone: 'Asia/Kuala_Lumpur', hour12: false, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch { return match; }
  });
  // Elapsed [M:SS] or [H:MM:SS] → absolute MYT
  if (phaseStart) {
    out = out.replace(/\[(\d+):(\d{2})(?::(\d{2}))?\]/g, (_m, p1, p2, p3) => {
      const secs = p3 !== undefined
        ? parseInt(p1) * 3600 + parseInt(p2) * 60 + parseInt(p3)
        : parseInt(p1) * 60 + parseInt(p2);
      const abs = new Date(phaseStart.getTime() + secs * 1000);
      const myt = abs.toLocaleString('en-MY', { timeZone: 'Asia/Kuala_Lumpur', hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
      return `[${myt}]`;
    });
  }
  return out;
}

interface PhaseIMetrics {
  storyBudgets: { id: string; budget: number }[];
  spawnCount: number;
  undoCount: number;
  baselineTests: string | null;
  latestTests: string | null;
  latestFailing: string | null;
  lastAction: string | null;
  stashed: boolean;
}

/** Parse Phase I log lines into key operational metrics. */
function extractPhaseIMetrics(lines: string[]): PhaseIMetrics {
  const clean = lines.map(stripAnsi);
  const storyBudgets: { id: string; budget: number }[] = [];
  for (const l of clean) {
    const m = l.match(/\[I\]\s+Budget:\s+(\d+)s\s+for\s+((?:US|UT)-\d+)/);
    if (m) storyBudgets.push({ id: m[2], budget: parseInt(m[1]) });
  }
  const spawnCount = clean.filter(l => /\[spawn\]\s+Fresh claude instance/.test(l)).length;
  const undoCount  = clean.filter(l => /\[undo\]\s+Worktree reset/.test(l)).length;
  const baselineMatch = clean.find(l => /\[baseline\].*pre-story.*passing/.test(l));
  const baselineTests = baselineMatch?.match(/(\d+)\s+passing/)?.[1] ?? null;
  const testLines     = clean.filter(l => /\d+\s+passing/.test(l));
  const latestTests   = testLines[testLines.length - 1]?.match(/(\d+)\s+passing/)?.[1] ?? null;
  const failLines     = clean.filter(l => /\d+\s+failing/.test(l));
  const latestFailing = failLines[failLines.length - 1]?.match(/(\d+)\s+failing/)?.[1] ?? null;
  const actionLines   = clean.filter(l => /^\s*\[(spawn|baseline|undo|model|completeness|precontext|cache|speckit)\]/.test(l));
  const lastAction    = actionLines[actionLines.length - 1]?.trim() ?? null;
  const stashed       = clean.some(l => /Stash created/.test(l));
  return { storyBudgets, spawnCount, undoCount, baselineTests, latestTests, latestFailing, lastAction, stashed };
}

// ── Phase Trace types ────────────────────────────────────────────────────────

interface Substep {
  id: string;
  label: string;
  lines: string[];
  lineStart: number;
  lineEnd: number;
}

interface IterPhase {
  phase: string;
  label: string;
  lines: string[];
  lineStart: number;
  lineEnd: number;
  substeps?: Substep[];
  bypassed?: boolean;
}

interface Iteration {
  iter: number;
  phases: IterPhase[];
  lineStart: number;
  lineEnd: number;
}

interface PhaseOutputs {
  aiSuggestions: { stories?: unknown[] } | null;
  research: { stories?: unknown[] } | null;
  testStories: { stories?: unknown[] } | null;
  validated: { stories?: unknown[] } | null;
  overflow: { stories?: unknown[] } | null;
  checkpoint: { iter?: number; phase?: string; ts?: string } | null;
}

interface PhaseTraceData {
  iterations: Iteration[];
  phaseOutputs: PhaseOutputs;
  phaseEvents: Array<{ event?: string; type?: string; phase?: string; iteration?: number; duration_s?: number; ts?: string }>;
}

const PHASE_COLORS: Record<string, { bg: string; border: string; text: string; dot: string }> = {
  '0': { bg: 'bg-slate-50',   border: 'border-slate-300',   text: 'text-slate-700',   dot: 'bg-slate-500' },
  A:   { bg: 'bg-indigo-50',  border: 'border-indigo-200',  text: 'text-indigo-700',  dot: 'bg-indigo-500' },
  R:   { bg: 'bg-blue-50',    border: 'border-blue-200',    text: 'text-blue-700',    dot: 'bg-blue-500' },
  T:   { bg: 'bg-violet-50',  border: 'border-violet-200',  text: 'text-violet-700',  dot: 'bg-violet-500' },
  S:   { bg: 'bg-cyan-50',    border: 'border-cyan-200',    text: 'text-cyan-700',    dot: 'bg-cyan-500' },
  E:   { bg: 'bg-sky-50',     border: 'border-sky-200',     text: 'text-sky-700',     dot: 'bg-sky-500' },
  M:   { bg: 'bg-amber-50',   border: 'border-amber-200',   text: 'text-amber-700',   dot: 'bg-amber-500' },
  X:   { bg: 'bg-lime-50',    border: 'border-lime-200',    text: 'text-lime-700',    dot: 'bg-lime-500' },
  I:   { bg: 'bg-emerald-50', border: 'border-emerald-200', text: 'text-emerald-700', dot: 'bg-emerald-500' },
  V:   { bg: 'bg-teal-50',    border: 'border-teal-200',    text: 'text-teal-700',    dot: 'bg-teal-500' },
  P:   { bg: 'bg-purple-50',  border: 'border-purple-200',  text: 'text-purple-700',  dot: 'bg-purple-500' },
  C:   { bg: 'bg-rose-50',    border: 'border-rose-200',    text: 'text-rose-700',    dot: 'bg-rose-500' },
  L:   { bg: 'bg-fuchsia-50', border: 'border-fuchsia-200', text: 'text-fuchsia-700', dot: 'bg-fuchsia-500' },
  D:   { bg: 'bg-orange-50',  border: 'border-orange-200',  text: 'text-orange-700',  dot: 'bg-orange-500' },
};

const PHASE_NAMES: Record<string, string> = {
  '0': 'Clarify (Session Setup)', A: 'AI Suggestions', R: 'Research', T: 'Test Synthesis',
  S: 'Story Validate', E: 'Enrichment', M: 'Merge', X: 'Context Build',
  I: 'Implement', V: 'Validate', P: 'Push', C: 'Check Done', L: 'Learning', D: 'Loop Decision',
};

const SUBSTEP_NAMES: Record<string, string> = {
  '0-A': 'Constitution', '0-B': 'Focus', '0-C': 'Clarify', '0-D': 'Story Prep', '0-E': 'Options',
  'I/decompose': 'Decompose', 'I/retry': 'Retry', 'I/commit': 'Commit', 'I/revert': 'Revert',
  'I.5': 'Self-Review',
  'test-ratchet': 'Test Ratchet', 'security-scan': 'Security Scan', 'tag': 'Git Tag', 'CAPACITY': 'Capacity Guard',
};

/** Canonical phase order — phases sort by this index in the timeline. */
const PHASE_ORDER: Record<string, number> = {
  '0': 0, A: 1, R: 2, T: 3, S: 4, E: 5, M: 6, X: 7, I: 8, V: 9, P: 10, C: 11, L: 12, D: 13,
};

const PHASE_ENABLED_DEFAULTS: Record<string, boolean> = {
  A: true, R: false, T: true, S: true, E: true, M: true, X: true, I: true, V: true, P: true, C: true, L: true,
};

// Story shape inside phase output files
interface OutputFileStory {
  id?: string;
  title?: string;
  priority?: string;
  _source?: string;
  [key: string]: unknown;
}

const OUTPUT_FILE_PATHS: Record<string, string> = {
  aiSuggestions: '.spiral/_ai_suggestions_output.json',
  research:      '.spiral/_research_output.json',
  testStories:   '.spiral/_test_stories_output.json',
  validated:     '.spiral/_validated_stories.json',
  overflow:      '.spiral/_research_overflow.json',
};

const SOURCE_COLORS: Record<string, string> = {
  'test-fix':   'bg-violet-100 text-violet-700 border-violet-200',
  'research':   'bg-blue-100 text-blue-700 border-blue-200',
  'ai-example': 'bg-indigo-100 text-indigo-700 border-indigo-200',
  'seed':       'bg-slate-100 text-slate-600 border-slate-200',
};

const PRIORITY_BADGE: Record<string, string> = {
  critical: 'bg-red-100 text-red-700 border-red-200',
  high:     'bg-orange-100 text-orange-700 border-orange-200',
  medium:   'bg-yellow-100 text-yellow-700 border-yellow-200',
  low:      'bg-slate-100 text-slate-500 border-slate-200',
};

function PhaseTraceTab({ projectName, stories, activeStory }: { projectName: string; stories?: Story[]; activeStory: ActiveStoryInfo | null }) {
  const [traceData, setTraceData] = useState<PhaseTraceData | null>(null);
  const [selectedIter, setSelectedIter] = useState<number | null>(null);
  const [expandedPhases, setExpandedPhases] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [phaseEnabled, setPhaseEnabled] = useState<Record<string, boolean>>(PHASE_ENABLED_DEFAULTS);
  const [savingPhase, setSavingPhase] = useState<string | null>(null);
  const [phaseChanged, setPhaseChanged] = useState(false);
  const [selectedOutputFile, setSelectedOutputFile] = useState<keyof PhaseOutputs | null>(null);
  const [maximizedPhase, setMaximizedPhase] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [selectedPhaseNavKey, setSelectedPhaseNavKey] = useState<string | null>(null);
  const userSelectedRef = useRef(false);

  useEffect(() => {
    if (!maximizedPhase) return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setMaximizedPhase(null); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [maximizedPhase]);

  useEffect(() => {
    const load = async () => {
      try {
        const [traceRes, cfgRes] = await Promise.all([
          fetch(`/api/phase-trace?name=${encodeURIComponent(projectName)}`),
          fetch(`/api/phase-config?name=${encodeURIComponent(projectName)}`),
        ]);
        if (traceRes.ok) {
          const data = await traceRes.json() as PhaseTraceData;
          setTraceData(data);
          // Auto-select latest iteration only on first load (before user clicks)
          if (data.iterations.length > 0 && !userSelectedRef.current) {
            setSelectedIter(data.iterations[data.iterations.length - 1].iter);
          }
        }
        if (cfgRes.ok) {
          const cfg = await cfgRes.json() as Record<string, boolean>;
          setPhaseEnabled(cfg);
        }
      } catch { /* ignore */ }
      setLoading(false);
    };
    load();
    const interval = setInterval(load, 15_000);
    return () => clearInterval(interval);
  }, [projectName]);

  const togglePhaseEnabled = async (phaseId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const next = { ...phaseEnabled, [phaseId]: !phaseEnabled[phaseId] };
    setPhaseEnabled(next);
    setSavingPhase(phaseId);
    try {
      const res = await fetch(`/api/phase-config?name=${encodeURIComponent(projectName)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config: next }),
      });
      if (res.ok) {
        setPhaseChanged(true);
        setTimeout(() => setPhaseChanged(false), 60_000);
      }
    } catch { /* ignore */ }
    setSavingPhase(null);
  };

  if (loading) return <div className="p-6 text-slate-500">Loading phase trace data...</div>;
  if (!traceData || traceData.iterations.length === 0) {
    return (
      <div className="p-6 text-slate-500">
        No phase trace data yet. Start SPIRAL to see phase-by-phase output here.
        <div className="mt-2 text-xs text-slate-400">
          Phase traces are parsed from <code className="bg-slate-100 px-1 rounded">.spiral/_last_run.log</code>
        </div>
      </div>
    );
  }

  const togglePhase = (key: string) => {
    setExpandedPhases(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  const currentIter = traceData.iterations.find(i => i.iter === selectedIter) ?? traceData.iterations[traceData.iterations.length - 1];

  // Find phase_start and phase_end events for duration/timing display
  const phaseStartEvents = traceData.phaseEvents.filter(
    e => (e.event === 'phase_start' || e.type === 'phase_start') && e.iteration === currentIter.iter
  );
  const phaseEndEvents = traceData.phaseEvents.filter(
    e => (e.event === 'phase_end' || e.type === 'phase_end') && e.iteration === currentIter.iter
  );

  const getDuration = (phase: string): number | null => {
    const ev = phaseEndEvents.find(e => e.phase === phase);
    if (ev?.duration_s == null) return null;
    return Math.max(0, ev.duration_s);
  };

  const getStartTs = (phase: string): string | null => {
    const ev = phaseStartEvents.find(e => e.phase === phase);
    return ev?.ts ?? null;
  };

  const getEndTs = (phase: string): string | null => {
    const ev = phaseEndEvents.find(e => e.phase === phase);
    return ev?.ts ?? null;
  };

  /** Format duration as human-readable string */
  const fmtDuration = (s: number): string => {
    if (s >= 3600) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m ${s % 60}s`;
    if (s >= 60) return `${Math.floor(s / 60)}m ${s % 60}s`;
    return `${s}s`;
  };

  /** Format time as MYT HH:MM:SS */
  const fmtTime = (ts: string): string => {
    try {
      return new Date(ts).toLocaleString('en-MY', { timeZone: 'Asia/Kuala_Lumpur', hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch { return ts; }
  };

  // Compute iteration total duration from earliest start to latest end
  const iterStartTs = phaseStartEvents.length > 0
    ? phaseStartEvents.reduce((earliest, e) => (!earliest || (e.ts && e.ts < earliest) ? e.ts! : earliest), '')
    : null;
  const iterEndTs = phaseEndEvents.length > 0
    ? phaseEndEvents.reduce((latest, e) => (!latest || (e.ts && e.ts > latest) ? e.ts! : latest), '')
    : null;
  const iterTotalDuration = iterStartTs && iterEndTs
    ? Math.max(0, Math.round((new Date(iterEndTs).getTime() - new Date(iterStartTs).getTime()) / 1000))
    : null;

  // Phase output file summary
  const outputSummary = (phase: string): string | null => {
    if (phase === 'A' && traceData.phaseOutputs.aiSuggestions) {
      const count = traceData.phaseOutputs.aiSuggestions.stories?.length ?? 0;
      return count > 0 ? `${count} ai suggestions` : 'No suggestions';
    }
    if (phase === 'R' && traceData.phaseOutputs.research) {
      const count = traceData.phaseOutputs.research.stories?.length ?? 0;
      return count > 0 ? `${count} research stories` : 'No stories found';
    }
    if (phase === 'T' && traceData.phaseOutputs.testStories) {
      const count = traceData.phaseOutputs.testStories.stories?.length ?? 0;
      return count > 0 ? `${count} test-fix stories` : 'No test failures';
    }
    if (phase === 'S' && traceData.phaseOutputs.validated) {
      const count = traceData.phaseOutputs.validated.stories?.length ?? 0;
      return count > 0 ? `${count} validated stories` : 'No stories validated';
    }
    return null;
  };

  return (
    <div className="flex min-h-full">

      {/* ── Left navigation sidebar ─────────────────────────────────────── */}
      <aside className="w-52 shrink-0 sticky top-0 h-screen overflow-y-auto border-r border-slate-200 bg-white z-10">
        <div className="pt-4 pb-6 px-2">

          {/* Iteration selector */}
          <div className="mb-4 px-1">
            <div className="text-[9px] font-semibold text-slate-400 uppercase tracking-widest mb-2 px-2">Iteration</div>
            <div className="flex flex-wrap gap-1 px-1">
              {traceData.iterations.map(iter => (
                <button
                  key={iter.iter}
                  onClick={() => { userSelectedRef.current = true; setSelectedIter(iter.iter); setExpandedPhases(new Set()); setSelectedPhaseNavKey(null); }}
                  className={`px-2 py-0.5 text-xs font-mono rounded-md border transition-colors ${
                    iter.iter === currentIter.iter
                      ? 'bg-blue-600 text-white border-blue-600'
                      : 'bg-white text-slate-600 border-slate-200 hover:border-blue-300 hover:bg-blue-50'
                  }`}
                >
                  #{iter.iter}
                </button>
              ))}
            </div>
            {iterTotalDuration !== null && (
              <div className="mt-2 px-2 text-[10px] font-mono text-slate-500">
                Total: <span className="font-semibold text-blue-700">{fmtDuration(iterTotalDuration)}</span>
              </div>
            )}
          </div>

          {/* Phase list */}
          <div className="mb-1.5 px-3 text-[9px] font-semibold text-slate-400 uppercase tracking-widest">
            Phases
            <span className="ml-1 normal-case font-normal text-slate-300">
              ({currentIter.phases.filter(p => p.phase !== 'G').length})
            </span>
          </div>
          {currentIter.phases
            .filter(p => p.phase !== 'G')
            .sort((a, b) => (PHASE_ORDER[a.phase] ?? 99) - (PHASE_ORDER[b.phase] ?? 99))
            .map(phase => {
              const colors = PHASE_COLORS[phase.phase] ?? { bg: 'bg-slate-50', border: 'border-slate-200', text: 'text-slate-700', dot: 'bg-slate-400' };
              const phaseName = PHASE_NAMES[phase.phase] ?? `Phase ${phase.phase}`;
              const duration = getDuration(phase.phase);
              const isBypassed = phase.bypassed === true;
              const isNotYetRun = !isBypassed && (phase.label.endsWith('(not run)') || phase.lineStart === -1);
              const isSkipped = isBypassed || isNotYetRun;
              const isSelected = selectedPhaseNavKey === phase.phase;
              const isActive = phase.phase === 'I' && activeStory?.storyId != null;
              return (
                <button
                  key={phase.phase}
                  onClick={() => !isSkipped && setSelectedPhaseNavKey(isSelected ? null : phase.phase)}
                  className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg text-left transition-colors mb-0.5 ${
                    isSkipped
                      ? 'opacity-40 cursor-default'
                      : isSelected
                        ? `${colors.bg} border ${colors.border}`
                        : 'hover:bg-slate-50 border border-transparent text-slate-600'
                  }`}
                >
                  <div className={`w-2 h-2 rounded-full flex-shrink-0 ${isSkipped ? 'bg-slate-300' : colors.dot}`} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className={`text-[11px] font-mono font-bold ${isSelected ? colors.text : 'text-slate-700'}`}>
                        {phase.phase}
                      </span>
                      {isActive && (
                        <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse flex-shrink-0" />
                      )}
                      {isSelected && (
                        <span className="ml-auto w-1 h-1 rounded-full bg-blue-500 flex-shrink-0" />
                      )}
                    </div>
                    <div className={`text-[10px] truncate leading-tight ${isSelected ? colors.text : 'text-slate-500'}`}>
                      {phaseName}
                    </div>
                  </div>
                  <div className="flex flex-col items-end gap-0.5 ml-1 flex-shrink-0">
                    {isSkipped ? (
                      <span className="text-[9px] text-slate-400 bg-slate-100 px-1 rounded">
                        {isBypassed ? 'SKIP' : 'N/A'}
                      </span>
                    ) : duration !== null ? (
                      <span className={`text-[9px] font-mono font-semibold ${isSelected ? colors.text : 'text-blue-700'}`}>
                        {fmtDuration(duration)}
                      </span>
                    ) : null}
                    {!isSkipped && (
                      <button
                        onClick={(e) => { void togglePhaseEnabled(phase.phase, e); }}
                        title={phaseEnabled[phase.phase] !== false ? 'Phase enabled — click to disable' : 'Phase disabled — click to enable'}
                        className={`flex items-center gap-0.5 px-1 py-0.5 rounded text-[9px] font-semibold transition-all ${
                          savingPhase === phase.phase
                            ? 'opacity-50 bg-slate-100 text-slate-400'
                            : phaseEnabled[phase.phase] !== false
                              ? 'bg-emerald-50 border border-emerald-200 text-emerald-700 hover:bg-emerald-100'
                              : 'bg-slate-100 border border-slate-200 text-slate-400 hover:bg-slate-200'
                        }`}
                      >
                        <span className={`w-1 h-1 rounded-full ${phaseEnabled[phase.phase] !== false ? 'bg-emerald-500' : 'bg-slate-400'}`} />
                        {phaseEnabled[phase.phase] !== false ? 'ON' : 'OFF'}
                      </button>
                    )}
                  </div>
                </button>
              );
            })}
        </div>
      </aside>

      {/* ── Main content ────────────────────────────────────────────────── */}
      <div className="flex-1 min-w-0 p-6 space-y-4">

        {phaseChanged && (
          <div className="flex items-center justify-between gap-3 px-3 py-2 rounded-lg border border-amber-300 bg-amber-50 text-amber-800 text-xs font-medium">
            <span>⚠️ Phase settings saved. Restart Spiral for changes to take effect.</span>
            <button onClick={() => setPhaseChanged(false)} className="text-amber-500 hover:text-amber-700 font-bold text-sm leading-none">✕</button>
          </div>
        )}

        {/* Timestamps */}
        <div className="flex items-center justify-between">
          <div className="text-[10px] text-slate-400">Timestamps shown in Malaysia Time (MYT, UTC+8)</div>
          <div className="text-[10px] text-slate-400">Now: {new Date().toLocaleString('en-MY', { timeZone: 'Asia/Kuala_Lumpur', hour12: false })}</div>
        </div>

        {traceData.phaseOutputs.checkpoint && (
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <span className="font-medium">Checkpoint:</span>
            <span>Iteration {traceData.phaseOutputs.checkpoint.iter}, Phase {traceData.phaseOutputs.checkpoint.phase}</span>
            {traceData.phaseOutputs.checkpoint.ts && (
              <span className="text-slate-400">({formatMYT(traceData.phaseOutputs.checkpoint.ts)} · {timeAgo(traceData.phaseOutputs.checkpoint.ts)})</span>
            )}
          </div>
        )}

        {/* Iteration timing summary */}
        {(iterStartTs || iterEndTs) && (
          <div className="flex items-center gap-4 text-[11px] text-slate-500 bg-white/60 rounded-lg border border-slate-200 px-3 py-2">
            {iterStartTs && <span>Started: <span className="font-mono font-medium text-slate-700">{formatMYT(iterStartTs)}</span></span>}
            {iterEndTs && <span>Finished: <span className="font-mono font-medium text-slate-700">{formatMYT(iterEndTs)}</span></span>}
            {iterTotalDuration !== null && <span>Duration: <span className="font-mono font-semibold text-blue-700">{fmtDuration(iterTotalDuration)}</span></span>}
          </div>
        )}

        {/* ── Phase detail panel or empty state ── */}
        {(() => {
          if (!selectedPhaseNavKey) {
            return (
              <div className="flex flex-col items-center justify-center py-16 gap-3 text-center">
                <span className="text-4xl">🔬</span>
                <div>
                  <div className="text-sm font-medium text-slate-500">Select a phase</div>
                  <div className="text-xs text-slate-400 mt-1">Click any phase in the left sidebar to view its details and logs</div>
                </div>
              </div>
            );
          }

          const sortedPhases = currentIter.phases
            .filter(p => p.phase !== 'G')
            .sort((a, b) => (PHASE_ORDER[a.phase] ?? 99) - (PHASE_ORDER[b.phase] ?? 99));
          const phase = sortedPhases.find(p => p.phase === selectedPhaseNavKey);
          if (!phase) return <div className="text-sm text-slate-400">Phase not found</div>;

          const colors = PHASE_COLORS[phase.phase] ?? { bg: 'bg-slate-50', border: 'border-slate-200', text: 'text-slate-700', dot: 'bg-slate-400' };
          const phaseName = PHASE_NAMES[phase.phase] ?? `Phase ${phase.phase}`;
          const duration = getDuration(phase.phase);
          const startTs = getStartTs(phase.phase);
          const endTs = getEndTs(phase.phase);
          const summary = outputSummary(phase.phase);
          const key = selectedPhaseNavKey;
          const substeps: Substep[] = (phase as IterPhase & { substeps?: Substep[] }).substeps ?? [];
          const hasSubsteps = substeps.length > 0;
          const isBypassed = phase.bypassed === true;
          const isNotYetRun = !isBypassed && (phase.label.endsWith('(not run)') || phase.lineStart === -1);
          const isSkipped = isBypassed || isNotYetRun;

          return (
            <div className={`rounded-xl border ${isSkipped ? 'border-slate-200 bg-slate-50/50' : `${colors.border} ${colors.bg}`} overflow-hidden`}>
              {/* Phase header */}
              <div className={`flex items-center gap-3 px-4 py-3 border-b ${isSkipped ? 'border-slate-200' : `${colors.border} bg-white/30`}`}>
                <div className={`w-3 h-3 rounded-full ${colors.dot} flex-shrink-0`} />
                <span className={`text-sm font-bold font-mono ${colors.text}`}>Phase {phase.phase}</span>
                <span className={`text-sm font-semibold ${colors.text}`}>{phaseName}</span>
                {phase.label && phase.label !== phaseName && !isSkipped && (
                  <span className="text-xs text-slate-500 truncate">{phase.label}</span>
                )}
                {phase.phase === 'I' && !isSkipped && activeStory?.storyId && (
                  <span className="flex items-center gap-1.5 text-[10px] font-medium bg-amber-50 border border-amber-200 text-amber-700 px-2 py-0.5 rounded-full flex-shrink-0">
                    <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
                    {activeStory.storyId}
                    {activeStory.title && <span className="text-amber-600 truncate max-w-[140px]">{activeStory.title}</span>}
                  </span>
                )}
                <div className="ml-auto flex items-center gap-2 flex-shrink-0">
                  {isBypassed && <span className="text-[10px] text-slate-500 bg-slate-200 px-2 py-0.5 rounded-full font-medium">BYPASSED</span>}
                  {isNotYetRun && <span className="text-[10px] text-slate-400 bg-slate-100 px-2 py-0.5 rounded-full font-medium">NOT YET RUN</span>}
                  {!isSkipped && summary && <span className="text-[10px] text-slate-500 bg-white/60 px-2 py-0.5 rounded-full">{summary}</span>}
                  {!isSkipped && hasSubsteps && <span className="text-[10px] text-slate-500 bg-white/60 px-2 py-0.5 rounded-full">{substeps.length} steps</span>}
                  {!isSkipped && duration !== null && (
                    <span className="text-[10px] font-mono font-semibold text-blue-700 bg-blue-50 border border-blue-200 px-2 py-0.5 rounded-full">
                      {fmtDuration(duration)}
                    </span>
                  )}
                  {!isSkipped && endTs && (
                    <span className="text-[10px] font-mono text-slate-500 bg-white/60 px-2 py-0.5 rounded-full" title={`Completed: ${formatMYT(endTs)}`}>
                      {fmtTime(endTs)}
                    </span>
                  )}
                  {!isSkipped && <span className="text-[10px] text-slate-400">{phase.lines.length} lines</span>}
                </div>
              </div>

              {/* Phase detail body */}
              {!isSkipped && (
                <div>
                  {/* Story IDs mentioned in this phase */}
                  {(() => {
                    if (!stories || stories.length === 0) return null;
                    const stripAnsi = (s: string) => s.replace(/\x1b\[[0-9;]*[mGKHFJ]/g, '').replace(/\u001b\[[0-9;]*[mGKHFJ]/g, '');
                    const ids = new Set<string>();
                    for (const line of phase.lines) {
                      const m = stripAnsi(line).match(/(?:US|UT)-\d+/gi) ?? [];
                      for (const id of m) ids.add(id.toUpperCase());
                    }
                    if (ids.size === 0) return null;
                    const passed = [...ids].filter(id => stories.find(s => s.id === id)?.passes === true);
                    const pending = [...ids].filter(id => {
                      const s = stories.find(st => st.id === id);
                      return s && s.passes !== true;
                    });
                    const unknown = [...ids].filter(id => !stories.find(s => s.id === id));
                    return (
                      <div className="px-4 py-2 border-b border-slate-200/50 bg-white/40 flex flex-wrap items-center gap-1.5">
                        <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mr-1">Stories:</span>
                        {passed.map(id => (
                          <span key={id} className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold bg-emerald-100 text-emerald-700 border border-emerald-200">
                            ✓ {id}
                          </span>
                        ))}
                        {pending.map(id => (
                          <span key={id} className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold bg-amber-50 text-amber-700 border border-amber-200">
                            ○ {id}
                          </span>
                        ))}
                        {unknown.map(id => (
                          <span key={id} className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-[10px] font-mono text-slate-400 bg-slate-50 border border-slate-200">
                            {id}
                          </span>
                        ))}
                      </div>
                    );
                  })()}
                  {/* Timing detail */}
                  {(startTs || endTs || duration !== null) && (
                    <div className="flex items-center gap-4 px-4 py-2 text-[11px] text-slate-500 bg-white/50 border-b border-slate-200/50">
                      {startTs && <span>Start: <span className="font-mono font-medium text-slate-700">{formatMYT(startTs)}</span></span>}
                      {endTs && <span>End: <span className="font-mono font-medium text-slate-700">{formatMYT(endTs)}</span></span>}
                      {duration !== null && <span>Duration: <span className="font-mono font-semibold text-blue-700">{fmtDuration(duration)}</span></span>}
                    </div>
                  )}
                  {/* Phase I — Metrics Dashboard */}
                  {phase.phase === 'I' && (() => {
                    const m = extractPhaseIMetrics(phase.lines);
                    const hasData = m.storyBudgets.length > 0 || m.spawnCount > 0 || m.lastAction;
                    if (!hasData) return null;
                    const baseNum   = m.baselineTests ? parseInt(m.baselineTests) : null;
                    const latestNum = m.latestTests   ? parseInt(m.latestTests)   : null;
                    const testColor = baseNum !== null && latestNum !== null
                      ? (latestNum >= baseNum ? 'text-emerald-600' : 'text-red-600')
                      : 'text-slate-700';
                    return (
                      <div className="px-4 py-3 border-b border-emerald-200/60 bg-emerald-50/70">
                        <div className="text-[10px] font-semibold text-emerald-700 uppercase tracking-wider mb-2.5">Phase I — Live Metrics</div>
                        <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-[11px]">
                          {/* Spawns / Undos */}
                          <div className="flex items-center gap-2">
                            <span className="text-slate-500 w-20 flex-shrink-0">Spawns:</span>
                            <span className="font-mono font-bold text-slate-700">{m.spawnCount}</span>
                            {m.undoCount > 0 && <span className="text-amber-600 font-mono text-[10px] bg-amber-50 border border-amber-200 rounded px-1">{m.undoCount} undo</span>}
                          </div>
                          {/* Tests */}
                          <div className="flex items-center gap-2">
                            <span className="text-slate-500 w-20 flex-shrink-0">Tests:</span>
                            {m.baselineTests && <span className="font-mono text-slate-400">{m.baselineTests} →</span>}
                            {latestNum !== null && <span className={`font-mono font-bold ${testColor}`}>{latestNum}</span>}
                            {m.latestFailing && parseInt(m.latestFailing) > 0 && (
                              <span className="font-mono font-bold text-red-600 bg-red-50 border border-red-200 rounded px-1">⚠ {m.latestFailing} failing</span>
                            )}
                            {!m.latestTests && <span className="text-slate-400">—</span>}
                          </div>
                          {/* Stories attempted */}
                          {m.storyBudgets.length > 0 && (
                            <div className="col-span-2 flex items-start gap-2">
                              <span className="text-slate-500 w-20 flex-shrink-0 pt-0.5">Stories:</span>
                              <div className="flex flex-wrap gap-1">
                                {m.storyBudgets.map((s, i) => (
                                  <span key={i} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-mono bg-emerald-100 text-emerald-700 border border-emerald-200">
                                    {s.id} <span className="text-emerald-500">{s.budget}s</span>
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}
                          {/* Last action */}
                          {m.lastAction && (
                            <div className="col-span-2 flex items-start gap-2">
                              <span className="text-slate-500 w-20 flex-shrink-0 pt-0.5">Last action:</span>
                              <span className="font-mono text-slate-600 text-[10px] break-all">{m.lastAction}</span>
                            </div>
                          )}
                          {/* Stash warning */}
                          {m.stashed && (
                            <div className="col-span-2 flex items-center gap-1.5 text-[10px] text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
                              ⚠ Working tree was auto-stashed before implementation
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })()}

                  {/* Sub-steps list */}
                  {hasSubsteps && (
                    <div className="px-4 py-3 space-y-1.5 border-b border-slate-200/50 bg-white/40">
                      <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Steps</div>
                      {substeps.map((sub: Substep, si: number) => {
                        const subKey = `${key}-sub-${si}`;
                        const subExpanded = expandedPhases.has(subKey);
                        const subName = SUBSTEP_NAMES[sub.id] ?? sub.id;
                        return (
                          <div key={subKey} className="rounded-lg border border-slate-200 bg-white overflow-hidden">
                            <button
                              onClick={(e) => { e.stopPropagation(); togglePhase(subKey); }}
                              className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-slate-50 transition-colors"
                            >
                              <span className="w-1.5 h-1.5 rounded-full bg-slate-400 flex-shrink-0" />
                              <span className="text-[11px] font-mono font-semibold text-slate-600">{sub.id}</span>
                              <span className="text-[11px] text-slate-500">{subName}</span>
                              {sub.label && sub.label !== subName && (
                                <span className="text-[10px] text-slate-400 truncate ml-1">{sub.label}</span>
                              )}
                              <span className="ml-auto text-[10px] text-slate-400">{sub.lines.length} lines</span>
                              <span className={`text-[10px] text-slate-400 transition-transform ${subExpanded ? 'rotate-180' : ''}`}>▼</span>
                            </button>
                            {subExpanded && (
                              <div className="border-t border-slate-800 bg-slate-950">
                                <div className="flex items-center justify-end px-2 py-1 bg-slate-900 border-b border-slate-800">
                                  {(() => {
                                    const subCopyKey = `sub-${key}-${si}`;
                                    const subCopied = copiedKey === subCopyKey;
                                    return (
                                      <button
                                        onClick={() => {
                                          void navigator.clipboard.writeText(sub.lines.map(l => processLogLine(l, startTs ? new Date(startTs) : null)).join('\n'));
                                          setCopiedKey(subCopyKey);
                                          setTimeout(() => setCopiedKey(prev => prev === subCopyKey ? null : prev), 2000);
                                        }}
                                        title="Copy log to clipboard"
                                        className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono transition-all ${
                                          subCopied ? 'bg-emerald-600 text-white' : 'bg-slate-700 hover:bg-slate-600 text-slate-300'
                                        }`}
                                      >
                                        {subCopied ? '✓ Copied' : '⎘ Copy'}
                                      </button>
                                    );
                                  })()}
                                </div>
                                <div className="overflow-auto max-h-[250px]">
                                  <pre className="p-2.5 text-[10px] text-slate-300 font-mono leading-relaxed whitespace-pre-wrap">
                                    {sub.lines.map(l => processLogLine(l, startTs ? new Date(startTs) : null)).join('\n')}
                                  </pre>
                                </div>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* Full phase log output */}
                  {(() => {
                    const phaseBaseDate = startTs ? new Date(startTs) : null;
                    const isMaximized = maximizedPhase === key;
                    const processed = phase.lines.map(l => processLogLine(l, phaseBaseDate));
                    const phaseCopyKey = `phase-${key}`;
                    const phaseCopied = copiedKey === phaseCopyKey;
                    const toolbar = (
                      <div className="flex items-center justify-between px-3 py-1.5 border-b border-slate-800 bg-slate-900">
                        <span className="text-[10px] text-slate-500 font-mono">
                          {phase.lines.length} lines{phase.phase === 'I' ? ' · elapsed→MYT' : ''}
                          {isMaximized && <span className="ml-2 text-blue-400">Phase {phase.phase} — {PHASE_NAMES[phase.phase] ?? phase.phase}</span>}
                        </span>
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => setMaximizedPhase(prev => prev === key ? null : key)}
                            title={isMaximized ? 'Restore to inline (Esc)' : 'Maximize to fullscreen'}
                            className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono transition-all ${
                              isMaximized ? 'bg-blue-600 text-white' : 'bg-slate-700 hover:bg-slate-600 text-slate-300'
                            }`}
                          >
                            {isMaximized ? '⊡ Restore' : '⊞ Max'}
                          </button>
                          <button
                            onClick={() => {
                              void navigator.clipboard.writeText(processed.join('\n'));
                              setCopiedKey(phaseCopyKey);
                              setTimeout(() => setCopiedKey(prev => prev === phaseCopyKey ? null : prev), 2000);
                            }}
                            title="Copy log to clipboard"
                            className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono transition-all ${
                              phaseCopied ? 'bg-emerald-600 text-white' : 'bg-slate-700 hover:bg-slate-600 text-slate-300'
                            }`}
                          >
                            {phaseCopied ? '✓ Copied' : '⎘ Copy'}
                          </button>
                        </div>
                      </div>
                    );
                    const logBody = (
                      <div className={`overflow-auto ${isMaximized ? 'flex-1' : 'max-h-[500px]'}`}>
                        <pre className="p-3 text-[11px] text-slate-300 font-mono leading-relaxed whitespace-pre-wrap">
                          {processed.join('\n')}
                        </pre>
                      </div>
                    );
                    if (isMaximized) {
                      return createPortal(
                        <div className="fixed inset-0 z-[9999] bg-slate-950 flex flex-col">
                          {toolbar}
                          {logBody}
                        </div>,
                        document.body
                      );
                    }
                    return (
                      <div className="bg-slate-950">
                        {toolbar}
                        {logBody}
                      </div>
                    );
                  })()}
                </div>
              )}
            </div>
          );
        })()}

        {/* Phase output files summary */}
        <div>
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Phase Output Files (Current)</div>
          <div className="grid grid-cols-2 gap-2">
            {[
              { label: 'AI Suggestions', key: 'aiSuggestions' as const, phase: 'A' },
              { label: 'Research Output', key: 'research' as const, phase: 'R' },
              { label: 'Test Stories', key: 'testStories' as const, phase: 'T' },
              { label: 'Validated Stories', key: 'validated' as const, phase: 'S' },
              { label: 'Overflow Queue', key: 'overflow' as const, phase: 'M' },
            ].map(item => {
              const data = traceData.phaseOutputs[item.key];
              const count = (data as { stories?: unknown[] } | null)?.stories?.length ?? 0;
              const colors = PHASE_COLORS[item.phase] ?? { bg: 'bg-slate-50', border: 'border-slate-200', text: 'text-slate-700', dot: 'bg-slate-400' };
              const isSelected = selectedOutputFile === item.key;
              const isClickable = !!data;
              return (
                <button
                  key={item.key}
                  disabled={!isClickable}
                  onClick={() => setSelectedOutputFile(isSelected ? null : item.key)}
                  className={`rounded-lg border px-3 py-2 flex items-center justify-between text-left w-full transition-all
                    ${colors.border} ${colors.bg}
                    ${isClickable ? 'cursor-pointer hover:brightness-95 active:scale-[0.99]' : 'cursor-default opacity-60'}
                    ${isSelected ? 'ring-2 ring-offset-1 ring-blue-400' : ''}
                  `}
                >
                  <div className="flex items-center gap-2">
                    <div className={`w-2 h-2 rounded-full ${colors.dot}`} />
                    <span className={`text-xs font-medium ${colors.text}`}>{item.label}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className={`text-xs font-mono ${count > 0 ? colors.text : 'text-slate-400'}`}>
                      {data ? `${count} stories` : 'N/A'}
                    </span>
                    {isClickable && (
                      <span className={`text-[10px] text-slate-400 transition-transform ${isSelected ? 'rotate-180' : ''}`}>▼</span>
                    )}
                  </div>
                </button>
              );
            })}
          </div>

          {/* Expandable detail panel */}
          {selectedOutputFile && (() => {
            const panelKey = selectedOutputFile;
            const panelData = traceData.phaseOutputs[panelKey] as { stories?: OutputFileStory[] } | null;
            const panelStories = panelData?.stories ?? [];
            const filePath = OUTPUT_FILE_PATHS[panelKey as string] ?? panelKey;
            return (
              <div className="mt-3 rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
                {/* Panel header */}
                <div className="flex items-center justify-between px-4 py-2.5 bg-slate-50 border-b border-slate-200">
                  <div className="flex items-center gap-3 min-w-0">
                    <span className="text-xs font-semibold text-slate-700">{panelStories.length} {panelStories.length === 1 ? 'story' : 'stories'}</span>
                    <code className="text-[11px] font-mono text-slate-500 truncate">{filePath}</code>
                  </div>
                  <button
                    onClick={() => setSelectedOutputFile(null)}
                    className="text-slate-400 hover:text-slate-600 text-xs leading-none ml-3 flex-shrink-0"
                    aria-label="Close panel"
                  >
                    ✕
                  </button>
                </div>

                {panelStories.length === 0 ? (
                  <div className="px-4 py-4 text-xs text-slate-400 italic">No stories in this file.</div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs border-collapse">
                      <thead>
                        <tr className="bg-slate-50 text-left text-[11px] text-slate-500 uppercase tracking-wide">
                          <th className="px-3 py-2 font-semibold w-[100px]">ID</th>
                          <th className="px-3 py-2 font-semibold">Title</th>
                          <th className="px-3 py-2 font-semibold w-[90px]">Priority</th>
                          <th className="px-3 py-2 font-semibold w-[110px]">Source</th>
                        </tr>
                      </thead>
                      <tbody>
                        {panelStories.map((s, idx) => {
                          const sid = s.id ?? `#${idx + 1}`;
                          const title = s.title ?? '—';
                          const priority = typeof s.priority === 'string' ? s.priority : null;
                          const source = typeof s._source === 'string' ? s._source : null;
                          return (
                            <tr key={sid} className="border-t border-slate-100 hover:bg-slate-50 transition-colors">
                              <td className="px-3 py-2 font-mono text-[11px] text-blue-700 whitespace-nowrap">{sid}</td>
                              <td className="px-3 py-2 text-slate-700 leading-snug">{title}</td>
                              <td className="px-3 py-2">
                                {priority ? (
                                  <span className={`inline-block text-[10px] px-1.5 py-0.5 rounded-full border font-medium ${PRIORITY_BADGE[priority] ?? 'bg-slate-100 text-slate-500 border-slate-200'}`}>
                                    {priority}
                                  </span>
                                ) : <span className="text-slate-300">—</span>}
                              </td>
                              <td className="px-3 py-2">
                                {source ? (
                                  <span className={`inline-block text-[10px] px-1.5 py-0.5 rounded-full border font-medium ${SOURCE_COLORS[source] ?? 'bg-slate-100 text-slate-500 border-slate-200'}`}>
                                    {source}
                                  </span>
                                ) : <span className="text-slate-300">—</span>}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            );
          })()}
        </div>
      </div>
    </div>
  );
}

export default PhaseTraceTab;
