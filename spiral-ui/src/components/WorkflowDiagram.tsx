import { useCallback } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  type Node,
  type Edge,
  type Connection,
  MarkerType,
  BackgroundVariant,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { ZONE_COLORS } from '../data/phases';

// ── Node Definitions ───────────────────────────────────────────────────────────

const initialNodes: Node[] = [
  // ── STARTUP ──────────────────────────────────────────────────────────────────
  { id: '0a', position: { x: 80,  y: 40  }, data: { label: '0-A Constitution', sub: 'Create / review rules', zone: 'startup' }, type: 'phase' },
  { id: '0b', position: { x: 80,  y: 140 }, data: { label: '0-B Focus', sub: 'Set session theme → SPIRAL_FOCUS', zone: 'startup' }, type: 'phase' },
  { id: '0c', position: { x: 80,  y: 240 }, data: { label: '0-C Clarify', sub: '3 questions to lock scope', zone: 'startup' }, type: 'phase' },
  { id: '0d', position: { x: 80,  y: 340 }, data: { label: '0-D Story Prep', sub: 'Seed → prd.json  |  AI pick → queue', zone: 'startup' }, type: 'phase' },
  { id: '0e', position: { x: 80,  y: 440 }, data: { label: '0-E Options', sub: 'Time limit · gate mode', zone: 'startup' }, type: 'phase' },

  // ── LOOP ─────────────────────────────────────────────────────────────────────
  { id: 'A',  position: { x: 460, y: 80  }, data: { label: 'A  AI Suggestions', sub: 'ai_suggest.py · generate_test_stories.py', zone: 'pipeline', sources: ['2','5'] }, type: 'phase' },
  { id: 'R',  position: { x: 340, y: 220 }, data: { label: 'R  Research', sub: 'Gemini → Claude agent', zone: 'pipeline', skip: '--skip-research · capacity · cache', sources: ['3'] }, type: 'phase' },
  { id: 'T',  position: { x: 600, y: 220 }, data: { label: 'T  Test Synthesis', sub: 'synthesize_tests.py', zone: 'pipeline', skip: 'memory pressure', sources: ['4'] }, type: 'phase' },
  { id: 'S',  position: { x: 460, y: 360 }, data: { label: 'S  Story Validate', sub: 'validate_stories.py', zone: 'pipeline' }, type: 'phase' },
  { id: 'M',  position: { x: 460, y: 480 }, data: { label: 'M  Merge', sub: 'merge_stories.py → prd.json', zone: 'pipeline' }, type: 'phase' },
  { id: 'G',  position: { x: 460, y: 590 }, data: { label: 'G  Gate', sub: '--gate proceed / skip / quit', zone: 'decision' }, type: 'decision' },
  { id: 'I',  position: { x: 460, y: 700 }, data: { label: 'I  Implement', sub: 'ralph.sh · Decompose → Execute → Commit', zone: 'implement' }, type: 'phase' },
  { id: 'V',  position: { x: 460, y: 820 }, data: { label: 'V  Validate', sub: 'SPIRAL_VALIDATE_CMD + persistent suites', zone: 'validate' }, type: 'phase' },
  { id: 'C',  position: { x: 460, y: 930 }, data: { label: 'C  Check Done', sub: 'all passes:true + 0 test failures?', zone: 'decision' }, type: 'decision' },

  // ── RALPH INNER LOOP ─────────────────────────────────────────────────────────
  { id: 'R1', position: { x: 860, y: 680 }, data: { label: 'Pick story', sub: 'priority + deps', zone: 'implement' }, type: 'ralph' },
  { id: 'R2', position: { x: 860, y: 760 }, data: { label: 'git branch', sub: '+ worktree', zone: 'implement' }, type: 'ralph' },
  { id: 'R3', position: { x: 860, y: 840 }, data: { label: 'Claude implements', sub: 'haiku / sonnet / opus', zone: 'implement' }, type: 'ralph' },
  { id: 'R4', position: { x: 860, y: 920 }, data: { label: 'Tests pass?', zone: 'decision' }, type: 'decision' },
  { id: 'R5', position: { x: 1000, y: 920 }, data: { label: 'Commit', sub: 'passes: true', zone: 'validate' }, type: 'ralph' },
  { id: 'R6', position: { x: 720, y: 920 }, data: { label: 'Revert + escalate', sub: 'haiku→sonnet→opus', zone: 'decision' }, type: 'ralph' },

  // ── TERMINAL NODES ───────────────────────────────────────────────────────────
  { id: 'DONE', position: { x: 600, y: 1040 }, data: { label: '🎉 SPIRAL COMPLETE', sub: '', zone: 'terminal' }, type: 'terminal' },
  { id: 'EXIT', position: { x: 320, y: 640 }, data: { label: '❌ Exit', sub: 'user quit', zone: 'terminal' }, type: 'terminal' },
];

// ── Custom Node Types ──────────────────────────────────────────────────────────

function PhaseNode({ data }: { data: { label: string; sub?: string; zone: string; skip?: string; sources?: string[] } }) {
  const colors = ZONE_COLORS[data.zone as keyof typeof ZONE_COLORS] ?? ZONE_COLORS.pipeline;
  return (
    <div
      className="rounded-lg px-3 py-2 text-xs shadow-md min-w-[160px] max-w-[200px] border-2"
      style={{ background: colors.bg, borderColor: colors.border, color: colors.text }}
    >
      <div className="font-bold text-sm leading-tight">{data.label}</div>
      {data.sub && <div className="mt-0.5 opacity-80 leading-snug">{data.sub}</div>}
      {data.skip && (
        <div className="mt-1 text-[10px] italic opacity-60">↷ skip: {data.skip}</div>
      )}
      {data.sources && (
        <div className="mt-1 flex gap-1 flex-wrap">
          {data.sources.map(s => (
            <span key={s} className="px-1 rounded text-[9px] font-bold" style={{ background: colors.border, color: '#fff' }}>
              Source {s}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function DecisionNode({ data }: { data: { label: string; sub?: string; zone: string } }) {
  const colors = ZONE_COLORS['decision'];
  return (
    <div
      className="px-3 py-2 text-xs shadow-md border-2 font-bold text-center min-w-[130px]"
      style={{
        background: colors.bg, borderColor: colors.border, color: colors.text,
        clipPath: 'polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)',
        paddingTop: '24px', paddingBottom: '24px', paddingLeft: '16px', paddingRight: '16px',
      }}
    >
      <div className="text-sm">{data.label}</div>
      {data.sub && <div className="text-[10px] opacity-70 mt-0.5">{data.sub}</div>}
    </div>
  );
}

function RalphNode({ data }: { data: { label: string; sub?: string; zone: string } }) {
  const colors = { bg: '#fce7f3', border: '#db2777', text: '#831843' };
  return (
    <div
      className="rounded px-3 py-1.5 text-xs shadow border-2 min-w-[130px]"
      style={{ background: colors.bg, borderColor: colors.border, color: colors.text }}
    >
      <div className="font-semibold">{data.label}</div>
      {data.sub && <div className="text-[10px] opacity-70">{data.sub}</div>}
    </div>
  );
}

function TerminalNode({ data }: { data: { label: string; sub?: string } }) {
  return (
    <div className="rounded-full px-4 py-2 text-xs font-bold shadow-lg border-2 border-emerald-600 bg-emerald-100 text-emerald-900 text-center min-w-[140px]">
      {data.label}
    </div>
  );
}

const nodeTypes = {
  phase: PhaseNode,
  decision: DecisionNode,
  ralph: RalphNode,
  terminal: TerminalNode,
};

// ── Edge Definitions ───────────────────────────────────────────────────────────

const edgeDefaults = {
  type: 'smoothstep' as const,
  markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
};

const initialEdges: Edge[] = [
  // Startup chain
  { id: 'e0a-0b', source: '0a', target: '0b', ...edgeDefaults },
  { id: 'e0b-0c', source: '0b', target: '0c', ...edgeDefaults },
  { id: 'e0c-0d', source: '0c', target: '0d', ...edgeDefaults },
  { id: 'e0d-0e', source: '0d', target: '0e', ...edgeDefaults },
  { id: 'e0e-A',  source: '0e', target: 'A', label: 'starts loop', ...edgeDefaults, style: { stroke: '#16a34a' } },

  // 0-D to prd (seed) — dashed
  { id: 'e0d-prd', source: '0d', target: 'A', label: 'seed → prd.json (direct)', ...edgeDefaults,
    style: { stroke: '#16a34a', strokeDasharray: '5,3' }, labelStyle: { fontSize: 9 } },

  // Phase A → R, T
  { id: 'eA-R', source: 'A', target: 'R', ...edgeDefaults, style: { stroke: '#2563eb' } },
  { id: 'eA-T', source: 'A', target: 'T', ...edgeDefaults, style: { stroke: '#2563eb' } },

  // R, T → S
  { id: 'eR-S', source: 'R', target: 'S', label: '_research_output.json', ...edgeDefaults, labelStyle: { fontSize: 9 } },
  { id: 'eT-S', source: 'T', target: 'S', label: '_test_stories_output.json', ...edgeDefaults, labelStyle: { fontSize: 9 } },
  { id: 'eA-S', source: 'A', target: 'S', label: '_ai_suggest + _test_story', ...edgeDefaults, labelStyle: { fontSize: 9 } },

  // S → M
  { id: 'eS-M', source: 'S', target: 'M', label: '_validated_stories.json', ...edgeDefaults },

  // M → G
  { id: 'eM-G', source: 'M', target: 'G', ...edgeDefaults },

  // G branches
  { id: 'eG-I', source: 'G', target: 'I', label: 'proceed', ...edgeDefaults, style: { stroke: '#16a34a' } },
  { id: 'eG-V', source: 'G', target: 'V', label: 'skip I', ...edgeDefaults, style: { stroke: '#ca8a04' }, labelStyle: { fontSize: 9 } },
  { id: 'eG-exit', source: 'G', target: 'EXIT', label: 'quit', ...edgeDefaults, style: { stroke: '#dc2626' } },

  // I → V → C
  { id: 'eI-V',  source: 'I', target: 'V', ...edgeDefaults },
  { id: 'eV-C',  source: 'V', target: 'C', ...edgeDefaults },

  // C branches
  { id: 'eC-done', source: 'C', target: 'DONE', label: '✅ all done', ...edgeDefaults, style: { stroke: '#059669' } },
  { id: 'eC-A', source: 'C', target: 'A', label: '⏳ pending', ...edgeDefaults,
    style: { stroke: '#2563eb', strokeDasharray: '6,3' }, type: 'straight' as const },

  // Ralph inner loop
  { id: 'eI-R1', source: 'I', target: 'R1', label: 'orchestrates', ...edgeDefaults,
    style: { stroke: '#db2777', strokeDasharray: '4,3' }, labelStyle: { fontSize: 9 } },
  { id: 'eR1-R2', source: 'R1', target: 'R2', ...edgeDefaults, style: { stroke: '#db2777' } },
  { id: 'eR2-R3', source: 'R2', target: 'R3', ...edgeDefaults, style: { stroke: '#db2777' } },
  { id: 'eR3-R4', source: 'R3', target: 'R4', ...edgeDefaults, style: { stroke: '#db2777' } },
  { id: 'eR4-R5', source: 'R4', target: 'R5', label: 'pass ✅', ...edgeDefaults, style: { stroke: '#059669' } },
  { id: 'eR4-R6', source: 'R4', target: 'R6', label: 'fail ❌', ...edgeDefaults, style: { stroke: '#dc2626' } },
  { id: 'eR6-R3', source: 'R6', target: 'R3', label: 'retry', ...edgeDefaults,
    style: { stroke: '#db2777', strokeDasharray: '4,3' } },
  { id: 'eR5-R1', source: 'R5', target: 'R1', ...edgeDefaults, style: { stroke: '#db2777', strokeDasharray: '4,3' } },
];

// ── Main Component ─────────────────────────────────────────────────────────────

export default function WorkflowDiagram() {
  const [nodes, , onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  const onConnect = useCallback((params: Connection) => {
    setEdges(eds => addEdge(params, eds));
  }, [setEdges]);

  return (
    <div className="w-full h-full" style={{ height: '100%' }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        minZoom={0.2}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#e2e8f0" />
        <Controls />
        <MiniMap
          nodeColor={node => {
            const zone = (node.data as { zone?: string })?.zone ?? 'pipeline';
            return ZONE_COLORS[zone as keyof typeof ZONE_COLORS]?.border ?? '#94a3b8';
          }}
          maskColor="rgba(255,255,255,0.7)"
        />
      </ReactFlow>
    </div>
  );
}
