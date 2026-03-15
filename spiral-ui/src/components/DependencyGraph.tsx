import { useEffect, useRef, useState } from 'react';
import mermaid from 'mermaid';

// ── Types ────────────────────────────────────────────────────────────────────

interface Story {
  id: string;
  title: string;
  passes: boolean;
  priority?: string;
  complexity?: string;
  failureReason?: string;
  dependencies?: string[];
  status?: string;
}

interface Props {
  stories: Story[];
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
      padding: 12,
    },
    securityLevel: 'loose', // needed for click callbacks
  });
  mermaidInitialized = true;
}

function getStatusColor(story: Story): string {
  const status = story.status?.toLowerCase();
  if (status === 'in_progress' || status === 'in-progress') return '#3b82f6'; // blue
  if (status === 'failed') return '#ef4444'; // red
  if (status === 'skipped') return '#eab308'; // yellow
  if (story.passes) return '#22c55e'; // green
  return '#94a3b8'; // grey (pending)
}

function getStatusTextColor(story: Story): string {
  const status = story.status?.toLowerCase();
  if (status === 'in_progress' || status === 'in-progress') return '#ffffff';
  if (status === 'failed') return '#ffffff';
  if (status === 'skipped') return '#1e293b';
  if (story.passes) return '#ffffff';
  return '#334155';
}

/** Sanitize an ID for use as a Mermaid node ID (no hyphens). */
function nodeId(id: string): string {
  return id.replace(/-/g, '_');
}

/** Truncate title to max 40 chars. */
function truncate(s: string, max = 40): string {
  return s.length > max ? s.slice(0, max - 1) + '…' : s;
}

/** Build the Mermaid LR flowchart string from stories. */
function buildMermaidDef(stories: Story[]): string {
  const lines: string[] = ['flowchart LR'];

  // Build a lookup for quick dependency checks
  const storyMap = new Map(stories.map(s => [s.id, s]));

  // Node definitions
  for (const s of stories) {
    const nid = nodeId(s.id);
    const label = `${s.id}<br/>${truncate(s.title)}`;
    const hasDeps = (s.dependencies ?? []).length > 0;
    // Stories with no dependencies use a different shape (stadium/rounded)
    const nodeDef = hasDeps
      ? `  ${nid}["${label}"]`
      : `  ${nid}(["${label}"])`;
    lines.push(nodeDef);
  }

  // Style definitions per node (color-coded by status)
  for (const s of stories) {
    const nid = nodeId(s.id);
    const bg = getStatusColor(s);
    const fg = getStatusTextColor(s);
    lines.push(`  style ${nid} fill:${bg},color:${fg},stroke:${bg}`);
  }

  // Edges (dependency arrows)
  for (const s of stories) {
    for (const dep of s.dependencies ?? []) {
      if (storyMap.has(dep)) {
        lines.push(`  ${nodeId(dep)} --> ${nodeId(s.id)}`);
      }
    }
  }

  // Click callbacks
  for (const s of stories) {
    lines.push(`  click ${nodeId(s.id)} spiralGraphClick_${nodeId(s.id)}`);
  }

  return lines.join('\n');
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

// ── Story Detail Panel ────────────────────────────────────────────────────────

function StoryDetailPanel({ story, onClose }: { story: Story; onClose: () => void }) {
  const statusColor = getStatusColor(story);
  const statusLabel = story.status ?? (story.passes ? 'passed' : 'pending');

  return (
    <div className="w-80 flex-shrink-0 h-full border-l border-slate-200 bg-white overflow-y-auto">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200">
        <span className="text-sm font-semibold text-slate-800">{story.id}</span>
        <button
          onClick={onClose}
          className="text-slate-400 hover:text-slate-600 text-lg leading-none"
          aria-label="Close"
        >
          ×
        </button>
      </div>
      <div className="p-4 space-y-3">
        <div>
          <div className="text-xs text-slate-400 uppercase tracking-wide mb-0.5">Title</div>
          <div className="text-sm text-slate-800">{story.title}</div>
        </div>
        <div className="flex gap-3">
          <div>
            <div className="text-xs text-slate-400 uppercase tracking-wide mb-0.5">Status</div>
            <span
              className="inline-block px-2 py-0.5 rounded text-xs font-medium"
              style={{ background: statusColor, color: getStatusTextColor(story) }}
            >
              {statusLabel}
            </span>
          </div>
          {story.priority && (
            <div>
              <div className="text-xs text-slate-400 uppercase tracking-wide mb-0.5">Priority</div>
              <div className="text-xs text-slate-700">{story.priority}</div>
            </div>
          )}
          {story.complexity && (
            <div>
              <div className="text-xs text-slate-400 uppercase tracking-wide mb-0.5">Complexity</div>
              <div className="text-xs text-slate-700">{story.complexity}</div>
            </div>
          )}
        </div>
        {(story.dependencies ?? []).length > 0 && (
          <div>
            <div className="text-xs text-slate-400 uppercase tracking-wide mb-1">Dependencies</div>
            <div className="flex flex-wrap gap-1">
              {(story.dependencies ?? []).map(dep => (
                <span key={dep} className="text-xs font-mono bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded">
                  {dep}
                </span>
              ))}
            </div>
          </div>
        )}
        {story.failureReason && (
          <div>
            <div className="text-xs text-red-400 uppercase tracking-wide mb-0.5">Failure Reason</div>
            <div className="text-xs text-red-700 bg-red-50 rounded p-2">{story.failureReason}</div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function DependencyGraph({ stories }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [selectedStory, setSelectedStory] = useState<Story | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const renderIdRef = useRef(0);

  useEffect(() => {
    initMermaid();
  }, []);

  useEffect(() => {
    if (!containerRef.current || stories.length === 0) return;

    const storyMap = new Map(stories.map(s => [s.id, s]));
    const renderId = ++renderIdRef.current;
    const def = buildMermaidDef(stories);
    const graphId = `spiral-dep-graph-${renderId}`;

    // Register global click handlers before rendering
    for (const s of stories) {
      const nid = nodeId(s.id);
      const handlerName = `spiralGraphClick_${nid}`;
      (window as unknown as Record<string, unknown>)[handlerName] = () => {
        const story = storyMap.get(s.id);
        if (story) setSelectedStory(story);
      };
    }

    mermaid.render(graphId, def)
      .then(({ svg }) => {
        if (renderIdRef.current !== renderId) return; // stale
        if (containerRef.current) {
          containerRef.current.innerHTML = svg;
          // Make SVG responsive
          const svgEl = containerRef.current.querySelector('svg');
          if (svgEl) {
            svgEl.style.maxWidth = '100%';
            svgEl.style.height = 'auto';
            svgEl.removeAttribute('height');
          }
          setRenderError(null);
        }
      })
      .catch(err => {
        if (renderIdRef.current !== renderId) return;
        setRenderError(String(err));
      });

    // Cleanup global handlers on next render
    return () => {
      for (const s of stories) {
        const nid = nodeId(s.id);
        delete (window as unknown as Record<string, unknown>)[`spiralGraphClick_${nid}`];
      }
    };
  }, [stories]); // re-render when stories change (on each poll)

  if (stories.length === 0) {
    return (
      <div className="p-6 text-slate-500 text-sm">
        No stories found. prd.json may be missing or empty.
      </div>
    );
  }

  return (
    <div className="flex h-full">
      {/* Graph area */}
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

      {/* Story detail panel */}
      {selectedStory && (
        <StoryDetailPanel
          story={selectedStory}
          onClose={() => setSelectedStory(null)}
        />
      )}
    </div>
  );
}
