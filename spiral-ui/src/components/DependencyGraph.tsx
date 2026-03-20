import { useCallback, useEffect, useRef, useState } from 'react';
import mermaid from 'mermaid';

// ── Types ────────────────────────────────────────────────────────────────────

interface Story {
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
}

interface StoryAttempt {
  timestamp: string;
  status: string;
  model: string;
  duration: number;
  commitSha: string;
}

interface Props {
  stories: Story[];
  storyAttempts?: Record<string, StoryAttempt[]>;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

let mermaidInitialized = false;

function initMermaid() {
  if (mermaidInitialized) return;
  mermaid.initialize({
    startOnLoad: false,
    theme: 'base',
    themeVariables: {
      primaryColor: '#e2e8f0',
      primaryTextColor: '#334155',
      primaryBorderColor: '#94a3b8',
      lineColor: '#94a3b8',
      background: '#f8fafc',
      mainBkg: '#f8fafc',
    },
    flowchart: {
      curve: 'basis',
      htmlLabels: true,
      padding: 8,
      nodeSpacing: 30,
      rankSpacing: 40,
    },
    securityLevel: 'loose',
  });
  mermaidInitialized = true;
}

function getStatusColor(story: Story): string {
  const status = story.status?.toLowerCase();
  if (status === 'in_progress' || status === 'in-progress') return '#3b82f6';
  if (status === 'failed') return '#ef4444';
  if (status === 'skipped') return '#eab308';
  if (story.passes) return '#22c55e';
  return '#94a3b8';
}

function getStatusTextColor(story: Story): string {
  const status = story.status?.toLowerCase();
  if (status === 'in_progress' || status === 'in-progress') return '#ffffff';
  if (status === 'failed') return '#ffffff';
  if (status === 'skipped') return '#1e293b';
  if (story.passes) return '#ffffff';
  return '#334155';
}

function nodeId(id: string): string {
  return id.replace(/-/g, '_');
}

/** Build the Mermaid LR flowchart — compact ID-only nodes. */
function buildMermaidDef(stories: Story[]): string {
  const lines: string[] = ['flowchart LR'];
  const storyMap = new Map(stories.map(s => [s.id, s]));

  for (const s of stories) {
    const nid = nodeId(s.id);
    const label = s.id;
    const hasDeps = (s.dependencies ?? []).length > 0;
    lines.push(hasDeps ? `  ${nid}["${label}"]` : `  ${nid}(["${label}"])`);
  }

  for (const s of stories) {
    const nid = nodeId(s.id);
    const bg = getStatusColor(s);
    const fg = getStatusTextColor(s);
    lines.push(`  style ${nid} fill:${bg},color:${fg},stroke:${bg},font-size:11px`);
  }

  for (const s of stories) {
    for (const dep of s.dependencies ?? []) {
      if (storyMap.has(dep)) {
        lines.push(`  ${nodeId(dep)} --> ${nodeId(s.id)}`);
      }
    }
  }

  return lines.join('\n');
}

function formatMYT(ts: string): string {
  try {
    return new Date(ts).toLocaleString('en-MY', { timeZone: 'Asia/Kuala_Lumpur', hour12: false });
  } catch { return ts; }
}

function timeAgo(ts: string) {
  const s = Math.floor((Date.now() - new Date(ts).getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m ago`;
}

// ── Legend ────────────────────────────────────────────────────────────────────

function GraphLegend() {
  const items = [
    { color: '#94a3b8', label: 'Pending' },
    { color: '#22c55e', label: 'Passed' },
    { color: '#3b82f6', label: 'In Progress' },
    { color: '#ef4444', label: 'Failed' },
    { color: '#eab308', label: 'Skipped' },
  ];
  return (
    <div className="flex flex-wrap gap-3 text-xs text-slate-600">
      {items.map(({ color, label }) => (
        <span key={label} className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-3 rounded-sm" style={{ background: color }} />
          {label}
        </span>
      ))}
      <span className="flex items-center gap-1.5 ml-3 text-slate-400">
        <span className="inline-block w-10 h-3 rounded-full border border-slate-300 bg-slate-100 text-center leading-3">oval</span>
        = no deps
      </span>
    </div>
  );
}

// ── Story Detail Panel (rich slide-in, matching progress page) ───────────────

function StoryDetailPanel({ story, allStories, attempts, onClose }: {
  story: Story;
  allStories: Story[];
  attempts?: StoryAttempt[];
  onClose: () => void;
}) {
  const PRIORITY_COLOR: Record<string, string> = {
    critical: 'bg-red-100 text-red-700 border-red-200',
    high: 'bg-orange-100 text-orange-700 border-orange-200',
    medium: 'bg-yellow-100 text-yellow-700 border-yellow-200',
    low: 'bg-slate-100 text-slate-500 border-slate-200',
  };
  const SOURCE_COLOR: Record<string, string> = {
    'test-fix': 'bg-rose-100 text-rose-700',
    research: 'bg-blue-100 text-blue-700',
    seed: 'bg-purple-100 text-purple-700',
    'ai-example': 'bg-slate-100 text-slate-500',
  };

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [onClose]);

  const storyMap = new Map(allStories.map(s => [s.id, s]));
  const passedCommit = attempts?.find(a => a.status === 'pass')?.commitSha ?? null;

  const [copiedSha, setCopiedSha] = useState(false);
  const copySha = (sha: string) => {
    navigator.clipboard.writeText(sha).then(() => {
      setCopiedSha(true);
      setTimeout(() => setCopiedSha(false), 2000);
    }).catch(() => { /* ignore */ });
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        className="relative z-10 bg-white shadow-2xl border-l border-slate-200 w-full max-w-lg h-full flex flex-col animate-slide-in-right"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start gap-3 px-6 py-4 border-b border-slate-100 flex-shrink-0">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs font-mono font-bold text-slate-500">{story.id}</span>
              {story.passes
                ? <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 border border-emerald-200 font-medium">&#10003; Complete</span>
                : <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 border border-amber-200 font-medium">&#9675; Pending</span>}
              {story.priority && (
                <span className={`text-[10px] px-2 py-0.5 rounded-full border font-medium ${PRIORITY_COLOR[story.priority] ?? 'bg-slate-100 text-slate-500 border-slate-200'}`}>
                  {story.priority}
                </span>
              )}
              {story.complexity && (
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700 border border-indigo-200 font-medium">{story.complexity}</span>
              )}
              {story.source && (
                <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${SOURCE_COLOR[story.source] ?? 'bg-slate-100 text-slate-500'}`}>{story.source}</span>
              )}
              {(story.retryCount ?? 0) > 0 && (
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-rose-50 text-rose-600 border border-rose-100 font-medium">{story.retryCount} retr{story.retryCount === 1 ? 'y' : 'ies'}</span>
              )}
            </div>
            <h2 className="mt-1.5 text-base font-semibold text-slate-800 leading-snug">{story.title}</h2>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-700 transition-colors p-1.5 rounded-lg hover:bg-slate-100 flex-shrink-0"
            title="Close (Esc)"
          >&#10005;</button>
        </div>

        {/* Body (scrollable) */}
        <div className="overflow-y-auto flex-1 px-6 py-4 space-y-5 text-sm">
          {story.description ? (
            <div>
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest mb-1.5">Description</div>
              <p className="text-slate-700 leading-relaxed whitespace-pre-wrap">{story.description}</p>
            </div>
          ) : (
            <div className="text-slate-400 italic text-xs">No description provided.</div>
          )}

          {story.acceptanceCriteria && story.acceptanceCriteria.length > 0 && (
            <div>
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest mb-1.5">Acceptance Criteria</div>
              <ul className="space-y-1.5">
                {story.acceptanceCriteria.map((c, i) => (
                  <li key={i} className="flex items-start gap-2 text-slate-700">
                    <span className={`mt-0.5 flex-shrink-0 ${story.passes ? 'text-emerald-500' : 'text-slate-300'}`}>
                      {story.passes ? '\u2713' : '\u25CB'}
                    </span>
                    <span className="leading-snug">{c}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {story.dependencies && story.dependencies.length > 0 && (
            <div>
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest mb-1.5">Dependencies</div>
              <div className="space-y-1">
                {story.dependencies.map(depId => {
                  const dep = storyMap.get(depId);
                  const passed = dep?.passes ?? false;
                  return (
                    <div key={depId} className="flex items-center gap-2">
                      <span className={`text-xs flex-shrink-0 ${passed ? 'text-emerald-500' : 'text-amber-500'}`}>
                        {passed ? '\u2713' : '\u25CB'}
                      </span>
                      <span className="font-mono text-[11px] text-blue-700 font-semibold">{depId}</span>
                      {dep && <span className="text-[11px] text-slate-500 truncate">{dep.title}</span>}
                      {!dep && <span className="text-[11px] text-slate-400 italic">not found</span>}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {story.filesTouch && story.filesTouch.length > 0 && (
            <div>
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest mb-1.5">Files</div>
              <div className="flex flex-wrap gap-1.5">
                {story.filesTouch.map((f, i) => (
                  <span key={i} className="font-mono text-[11px] bg-slate-100 text-slate-600 px-2 py-0.5 rounded">{f}</span>
                ))}
              </div>
            </div>
          )}

          {story.failureReason && (
            <div>
              <div className="text-[10px] font-semibold text-red-400 uppercase tracking-widest mb-1.5">Failure Reason</div>
              <div className="text-xs text-red-700 bg-red-50 rounded p-2 whitespace-pre-wrap">{story.failureReason}</div>
            </div>
          )}

          {attempts && attempts.length > 0 && (
            <div>
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest mb-1.5">Attempt History</div>
              <div className="rounded-lg border border-slate-200 overflow-hidden">
                <table className="w-full text-xs">
                  <thead className="bg-slate-50 text-slate-500">
                    <tr>
                      <th className="px-2.5 py-1.5 text-left">Time</th>
                      <th className="px-2.5 py-1.5 text-left">Model</th>
                      <th className="px-2.5 py-1.5 text-left">Status</th>
                      <th className="px-2.5 py-1.5 text-right">Duration</th>
                    </tr>
                  </thead>
                  <tbody>
                    {attempts.map((a, i) => (
                      <tr key={i} className="border-t border-slate-100">
                        <td className="px-2.5 py-1.5 text-slate-500" title={formatMYT(a.timestamp)}>{timeAgo(a.timestamp)}</td>
                        <td className="px-2.5 py-1.5 text-slate-600 font-mono">{a.model || '\u2014'}</td>
                        <td className="px-2.5 py-1.5">
                          <span className={`inline-block text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                            a.status === 'pass' ? 'bg-emerald-100 text-emerald-700' :
                            a.status === 'reject' ? 'bg-red-100 text-red-700' :
                            'bg-slate-100 text-slate-500'
                          }`}>{a.status}</span>
                        </td>
                        <td className="px-2.5 py-1.5 text-right text-slate-500">
                          {a.duration >= 60 ? `${Math.floor(a.duration / 60)}m ${a.duration % 60}s` : `${a.duration}s`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {passedCommit && (
            <div>
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest mb-1.5">Commit</div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-[11px] text-slate-600 bg-slate-100 px-2 py-0.5 rounded">{passedCommit.slice(0, 8)}</span>
                <button
                  onClick={() => copySha(passedCommit)}
                  className="text-[10px] text-blue-600 hover:text-blue-800"
                >{copiedSha ? 'Copied!' : 'Copy'}</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function DependencyGraph({ stories, storyAttempts }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [selectedStory, setSelectedStory] = useState<Story | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const renderIdRef = useRef(0);

  useEffect(() => {
    initMermaid();
  }, []);

  // Attach tooltips and click listeners directly to SVG nodes after render
  const enhanceNodes = useCallback((storyMap: Map<string, Story>) => {
    if (!containerRef.current) return;
    const svgEl = containerRef.current.querySelector('svg');
    if (!svgEl) return;

    const nodeGroups = svgEl.querySelectorAll('.node');
    nodeGroups.forEach((node) => {
      const nodeAttrId = node.id || '';
      const match = nodeAttrId.match(/flowchart-([\w]+)-/);
      if (!match) return;

      const nid = match[1];
      const storyId = nid.replace(/_/g, '-');
      const story = storyMap.get(storyId);
      if (!story) return;

      // Hover tooltip
      const existingTitle = node.querySelector('title');
      if (existingTitle) existingTitle.remove();
      const titleEl = document.createElementNS('http://www.w3.org/2000/svg', 'title');
      titleEl.textContent = story.title;
      node.insertBefore(titleEl, node.firstChild);

      // Click handler + pointer cursor
      (node as SVGElement).style.cursor = 'pointer';
      node.addEventListener('click', (e) => {
        e.stopPropagation();
        setSelectedStory(story);
      });
    });
  }, []);

  useEffect(() => {
    if (!containerRef.current || stories.length === 0) return;

    const storyMap = new Map(stories.map(s => [s.id, s]));
    const renderId = ++renderIdRef.current;
    const def = buildMermaidDef(stories);
    const graphId = `spiral-dep-graph-${renderId}`;

    mermaid.render(graphId, def)
      .then(({ svg }) => {
        if (renderIdRef.current !== renderId) return;
        if (containerRef.current) {
          containerRef.current.innerHTML = svg;
          const svgEl = containerRef.current.querySelector('svg');
          if (svgEl) {
            svgEl.style.maxWidth = '100%';
            svgEl.style.height = 'auto';
            svgEl.removeAttribute('height');
          }
          setRenderError(null);
          enhanceNodes(storyMap);
        }
      })
      .catch(err => {
        if (renderIdRef.current !== renderId) return;
        setRenderError(String(err));
      });
  }, [stories, enhanceNodes]);

  if (stories.length === 0) {
    return (
      <div className="p-6 text-slate-500 text-sm">
        No stories found. prd.json may be missing or empty.
      </div>
    );
  }

  return (
    <div className="flex h-full">
      <div className="flex-1 min-w-0 flex flex-col">
        <div className="px-6 pt-4 pb-2 flex-shrink-0">
          <GraphLegend />
        </div>
        {renderError && (
          <div className="mx-6 mb-3 p-3 bg-red-50 border border-red-200 rounded text-xs text-red-700">
            Graph render error: {renderError}
          </div>
        )}
        <div className="flex-1 overflow-auto px-6 pb-6">
          <div
            ref={containerRef}
            className="min-w-0"
            style={{ minHeight: 200 }}
          />
        </div>
      </div>

      {selectedStory && (
        <StoryDetailPanel
          story={selectedStory}
          allStories={stories}
          attempts={storyAttempts?.[selectedStory.id]}
          onClose={() => setSelectedStory(null)}
        />
      )}
    </div>
  );
}
