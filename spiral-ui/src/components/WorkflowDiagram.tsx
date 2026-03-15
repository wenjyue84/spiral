import { useCallback, useEffect } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  useNodesState,
  useEdgesState,
  addEdge,
  type Node,
  type Edge,
  type NodeProps,
  type Connection,
  MarkerType,
  BackgroundVariant,
} from '@xyflow/react';
import { ZONE_COLORS } from '../data/phases';

// ── Props ───────────────────────────────────────────────────────────────────────

interface WorkflowDiagramProps {
  selectedNodeId?: string | null;
  onNodeSelect?: (id: string | null, label: string, sub: string, zone: string) => void;
}

// ── Node Definitions ───────────────────────────────────────────────────────────

const initialNodes: Node[] = [
  // ── STAGE GROUP BACKGROUNDS (rendered first = behind all other nodes) ─────────
  { id: 'grp-startup',  position: { x: 45,  y: 10  }, data: { label: '① Startup — Session Setup',       color: '#16a34a', width: 250, height: 540 }, type: 'group', draggable: false, selectable: false, focusable: false, zIndex: -1 },
  { id: 'grp-pipeline', position: { x: 300, y: 55  }, data: { label: '② Pipeline — Preparing Stories',  color: '#2563eb', width: 560, height: 535 }, type: 'group', draggable: false, selectable: false, focusable: false, zIndex: -1 },
  { id: 'grp-impl',     position: { x: 425, y: 555 }, data: { label: '③ Implement & Validate',          color: '#ea580c', width: 760, height: 665 }, type: 'group', draggable: false, selectable: false, focusable: false, zIndex: -1 },

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

  // ── DISCOVERY CHECK (always loops back — no exit here) ───────────────────────
  { id: 'D',  position: { x: 460, y: 1050 }, data: { label: 'D  AI Suggestions', sub: 'Phase A always finds improvements', zone: 'decision' }, type: 'decision' },

  // ── TERMINAL NODES ───────────────────────────────────────────────────────────
  { id: 'DONE', position: { x: 460, y: 1180 }, data: { label: '🏁 SPIRAL ENDS', sub: 'max iters / time limit / cost ceiling', zone: 'terminal' }, type: 'terminal' },
  { id: 'EXIT', position: { x: 320, y: 640 }, data: { label: '❌ Exit', sub: 'user quit', zone: 'terminal' }, type: 'terminal' },
];

// ── Custom Node Types ──────────────────────────────────────────────────────────

type PhaseData = { label: string; sub?: string; zone: string; skip?: string; sources?: string[] };

const hStyle  = { opacity: 0, width: 6, height: 6, minWidth: 6, minHeight: 6 };
const hStyleL = { opacity: 0, width: 8, height: 8, minWidth: 8, minHeight: 8 }; // named left handles for loop edges

function PhaseNode({ data, selected, id }: NodeProps & { data: PhaseData }) {
  const colors = ZONE_COLORS[data.zone as keyof typeof ZONE_COLORS] ?? ZONE_COLORS.pipeline;
  // Node A gets a named left handle so the discovery loop-back can anchor to it
  const isLoopTarget = id === 'A';
  return (
    <>
      <Handle type="target" position={Position.Top}    style={hStyle} isConnectable={false} />
      <Handle type="target" position={Position.Left}   style={isLoopTarget ? hStyleL : hStyle} id={isLoopTarget ? 'loop-in' : undefined} isConnectable={false} />
      <div
        className="rounded-lg px-3 py-2 text-xs shadow-md min-w-[160px] max-w-[200px] border-2 cursor-pointer transition-all"
        style={{
          background: colors.bg,
          borderColor: selected ? '#1d4ed8' : colors.border,
          color: colors.text,
          boxShadow: selected ? `0 0 0 3px #93c5fd, 0 4px 12px rgba(0,0,0,0.15)` : undefined,
          transform: selected ? 'scale(1.03)' : undefined,
        }}
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
        {selected && (
          <div className="mt-1 text-[9px] font-semibold text-blue-600 opacity-80">Click to configure ↗</div>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} style={hStyle} isConnectable={false} />
      <Handle type="source" position={Position.Right}  style={hStyle} isConnectable={false} />
    </>
  );
}

type SimpleData = { label: string; sub?: string; zone: string };

function DecisionNode({ data, selected, id }: NodeProps & { data: SimpleData }) {
  const colors = ZONE_COLORS['decision'];
  const isLoopSource = id === 'D' || id === 'C';
  return (
    <>
      <Handle type="target" position={Position.Top}    style={hStyle} isConnectable={false} />
      <Handle type="target" position={Position.Left}   style={hStyle} isConnectable={false} />
      <div
        className="px-3 py-2 text-xs shadow-md border-2 font-bold text-center min-w-[130px] cursor-pointer transition-all"
        style={{
          background: colors.bg,
          borderColor: selected ? '#1d4ed8' : colors.border,
          color: colors.text,
          clipPath: 'polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)',
          paddingTop: '24px', paddingBottom: '24px', paddingLeft: '16px', paddingRight: '16px',
          boxShadow: selected ? `0 0 0 3px #93c5fd` : undefined,
        }}
      >
        <div className="text-sm">{data.label}</div>
        {data.sub && <div className="text-[10px] opacity-70 mt-0.5">{data.sub}</div>}
      </div>
      <Handle type="source" position={Position.Bottom} style={hStyle} isConnectable={false} />
      <Handle type="source" position={Position.Right}  style={hStyle} isConnectable={false} />
      {isLoopSource && (
        <Handle type="source" position={Position.Left} style={hStyleL} id="loop-out" isConnectable={false} />
      )}
    </>
  );
}

function RalphNode({ data, selected }: NodeProps & { data: SimpleData }) {
  const colors = { bg: '#fce7f3', border: '#db2777', text: '#831843' };
  return (
    <>
      <Handle type="target" position={Position.Top}    style={hStyle} isConnectable={false} />
      <Handle type="target" position={Position.Left}   style={hStyle} isConnectable={false} />
      <div
        className="rounded px-3 py-1.5 text-xs shadow border-2 min-w-[130px] cursor-pointer transition-all"
        style={{
          background: colors.bg,
          borderColor: selected ? '#1d4ed8' : colors.border,
          color: colors.text,
          boxShadow: selected ? `0 0 0 3px #93c5fd` : undefined,
        }}
      >
        <div className="font-semibold">{data.label}</div>
        {data.sub && <div className="text-[10px] opacity-70">{data.sub}</div>}
      </div>
      <Handle type="source" position={Position.Bottom} style={hStyle} isConnectable={false} />
      <Handle type="source" position={Position.Right}  style={hStyle} isConnectable={false} />
    </>
  );
}

function TerminalNode({ data, selected }: NodeProps & { data: { label: string; sub?: string } }) {
  return (
    <>
      <Handle type="target" position={Position.Top}    style={hStyle} isConnectable={false} />
      <Handle type="target" position={Position.Left}   style={hStyle} isConnectable={false} />
      <div
        className="rounded-full px-4 py-2 text-xs font-bold shadow-lg border-2 border-emerald-600 bg-emerald-100 text-emerald-900 text-center min-w-[140px] cursor-pointer transition-all"
        style={{ boxShadow: selected ? `0 0 0 3px #93c5fd` : undefined }}
      >
        {data.label}
      </div>
      <Handle type="source" position={Position.Bottom} style={hStyle} isConnectable={false} />
      <Handle type="source" position={Position.Right}  style={hStyle} isConnectable={false} />
    </>
  );
}

type GroupData = { label: string; color: string; width: number; height: number };

function GroupNode({ data }: NodeProps & { data: GroupData }) {
  return (
    <div style={{
      width: data.width,
      height: data.height,
      border: `2px dashed ${data.color}`,
      borderRadius: 14,
      background: `${data.color}12`,
      pointerEvents: 'none',
      position: 'relative',
      overflow: 'visible',
    }}>
      <div style={{
        position: 'absolute',
        top: -15,
        left: 14,
        background: data.color,
        color: '#fff',
        fontSize: 10,
        fontWeight: 700,
        padding: '2px 10px',
        borderRadius: 6,
        letterSpacing: '0.08em',
        textTransform: 'uppercase',
        whiteSpace: 'nowrap',
        boxShadow: '0 1px 4px rgba(0,0,0,0.18)',
      }}>
        {data.label}
      </div>
    </div>
  );
}

const nodeTypes = {
  phase: PhaseNode,
  decision: DecisionNode,
  ralph: RalphNode,
  terminal: TerminalNode,
  group: GroupNode,
};

// ── Edge Definitions ───────────────────────────────────────────────────────────

const arrow = { type: MarkerType.ArrowClosed, width: 20, height: 20 };

const edgeDefaults = {
  type: 'smoothstep' as const,
  markerEnd: arrow,
  style: { strokeWidth: 2, stroke: '#94a3b8' },
};

const initialEdges: Edge[] = [
  // Startup chain
  { id: 'e0a-0b', source: '0a', target: '0b', ...edgeDefaults },
  { id: 'e0b-0c', source: '0b', target: '0c', ...edgeDefaults },
  { id: 'e0c-0d', source: '0c', target: '0d', ...edgeDefaults },
  { id: 'e0d-0e', source: '0d', target: '0e', ...edgeDefaults },
  { id: 'e0e-A',  source: '0e', target: 'A', label: 'starts loop', ...edgeDefaults, style: { stroke: '#16a34a', strokeWidth: 2.5 } },

  // 0-D to prd (seed) — dashed
  { id: 'e0d-prd', source: '0d', target: 'A', label: 'seed → prd.json (direct)', ...edgeDefaults,
    style: { stroke: '#16a34a', strokeDasharray: '5,3', strokeWidth: 1.5 }, labelStyle: { fontSize: 9 } },

  // Phase A → R, T
  { id: 'eA-R', source: 'A', target: 'R', ...edgeDefaults, style: { stroke: '#2563eb', strokeWidth: 2 } },
  { id: 'eA-T', source: 'A', target: 'T', ...edgeDefaults, style: { stroke: '#2563eb', strokeWidth: 2 } },

  // R, T → S
  { id: 'eR-S', source: 'R', target: 'S', label: '_research_output.json', ...edgeDefaults, style: { strokeWidth: 1.5 }, labelStyle: { fontSize: 9 } },
  { id: 'eT-S', source: 'T', target: 'S', label: '_test_stories_output.json', ...edgeDefaults, style: { strokeWidth: 1.5 }, labelStyle: { fontSize: 9 } },
  { id: 'eA-S', source: 'A', target: 'S', label: '_ai_suggest + _test_story', ...edgeDefaults, style: { strokeWidth: 1.5 }, labelStyle: { fontSize: 9 } },

  // S → M
  { id: 'eS-M', source: 'S', target: 'M', label: '_validated_stories.json', ...edgeDefaults, style: { strokeWidth: 2 } },

  // M → G
  { id: 'eM-G', source: 'M', target: 'G', ...edgeDefaults, style: { strokeWidth: 2 } },

  // G branches
  { id: 'eG-I',    source: 'G', target: 'I',    label: 'proceed', ...edgeDefaults, style: { stroke: '#16a34a', strokeWidth: 2.5 } },
  { id: 'eG-V',    source: 'G', target: 'V',    label: 'skip I',  ...edgeDefaults, style: { stroke: '#ca8a04', strokeWidth: 2 }, labelStyle: { fontSize: 9 } },
  { id: 'eG-exit', source: 'G', target: 'EXIT', label: 'quit',    ...edgeDefaults, style: { stroke: '#dc2626', strokeWidth: 2 } },

  // I → V → C
  { id: 'eI-V', source: 'I', target: 'V', ...edgeDefaults, style: { strokeWidth: 2 } },
  { id: 'eV-C', source: 'V', target: 'C', ...edgeDefaults, style: { strokeWidth: 2 } },

  // C branches — pending stories loop immediately; all-done goes to Discovery Check
  { id: 'eC-A',  source: 'C', target: 'A', label: '⏳ pending stories',
    ...edgeDefaults,
    style: { stroke: '#2563eb', strokeDasharray: '6,3', strokeWidth: 2.5 },
    markerEnd: { ...arrow, color: '#2563eb' },
    labelStyle: { fontSize: 9, fontWeight: 600 },
    sourceHandle: 'loop-out',
    targetHandle: 'loop-in' },
  { id: 'eC-D',  source: 'C', target: 'D', label: '✅ all complete', ...edgeDefaults,
    style: { stroke: '#059669', strokeWidth: 2.5 } },

  // D → A: ALWAYS loops — Phase A can always suggest improvements, no exit here
  { id: 'eD-A',  source: 'D', target: 'A',
    label: '♻️ always loops — no perfect system',
    ...edgeDefaults,
    style: { stroke: '#16a34a', strokeWidth: 3.5, strokeDasharray: '10,5' },
    markerEnd: { ...arrow, color: '#16a34a', width: 24, height: 24 },
    labelStyle: { fontSize: 10, fontWeight: 700, fill: '#15803d' },
    type: 'smoothstep' as const,
    sourceHandle: 'loop-out',
    targetHandle: 'loop-in',
  },
  // DONE is only reached when max iters / time limit / cost ceiling is hit (outer loop exits)
  { id: 'eD-done', source: 'D', target: 'DONE',
    label: 'max iters / time limit',
    ...edgeDefaults,
    style: { stroke: '#94a3b8', strokeWidth: 1.5, strokeDasharray: '4,4' },
    labelStyle: { fontSize: 9, fill: '#64748b' } },

  // Ralph inner loop
  { id: 'eI-R1', source: 'I', target: 'R1', label: 'orchestrates', ...edgeDefaults,
    style: { stroke: '#db2777', strokeDasharray: '4,3', strokeWidth: 2 }, labelStyle: { fontSize: 9 } },
  { id: 'eR1-R2', source: 'R1', target: 'R2', ...edgeDefaults, style: { stroke: '#db2777', strokeWidth: 2 } },
  { id: 'eR2-R3', source: 'R2', target: 'R3', ...edgeDefaults, style: { stroke: '#db2777', strokeWidth: 2 } },
  { id: 'eR3-R4', source: 'R3', target: 'R4', ...edgeDefaults, style: { stroke: '#db2777', strokeWidth: 2 } },
  { id: 'eR4-R5', source: 'R4', target: 'R5', label: 'pass ✅', ...edgeDefaults, style: { stroke: '#059669', strokeWidth: 2.5 } },
  { id: 'eR4-R6', source: 'R4', target: 'R6', label: 'fail ❌', ...edgeDefaults, style: { stroke: '#dc2626', strokeWidth: 2.5 } },
  { id: 'eR6-R3', source: 'R6', target: 'R3', label: 'retry', ...edgeDefaults,
    style: { stroke: '#db2777', strokeDasharray: '4,3', strokeWidth: 2 } },
  { id: 'eR5-R1', source: 'R5', target: 'R1', ...edgeDefaults,
    style: { stroke: '#db2777', strokeDasharray: '4,3', strokeWidth: 2 } },
];

// ── Main Component ─────────────────────────────────────────────────────────────

export default function WorkflowDiagram({ selectedNodeId, onNodeSelect }: WorkflowDiagramProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  // Sync selected state into nodes so custom components receive `selected` prop
  useEffect(() => {
    setNodes(nds => nds.map(n => ({ ...n, selected: n.id === selectedNodeId })));
  }, [selectedNodeId, setNodes]);

  const onConnect = useCallback((params: Connection) => {
    setEdges(eds => addEdge(params, eds));
  }, [setEdges]);

  const handleNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    const d = node.data as PhaseData;
    onNodeSelect?.(node.id, String(d.label ?? node.id), String(d.sub ?? ''), String(d.zone ?? 'pipeline'));
  }, [onNodeSelect]);

  const handlePaneClick = useCallback(() => {
    onNodeSelect?.(null, '', '', '');
  }, [onNodeSelect]);

  return (
    <div className="w-full h-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={handleNodeClick}
        onPaneClick={handlePaneClick}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        minZoom={0.2}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{ style: { strokeWidth: 2 } }}
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
