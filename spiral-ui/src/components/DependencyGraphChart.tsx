import { useEffect, useState } from 'react';

interface GNode { id: string; title: string; sub_project: string; passes: boolean; }
interface GEdge { from: string; to: string; from_project: string; to_project: string; reason: string; }
interface GraphData { sub_projects: string[]; nodes: GNode[]; edges: GEdge[]; }
type Sel = { type: 'node'; data: GNode } | { type: 'edge'; data: GEdge } | null;

const COLORS = ['#3b82f6','#8b5cf6','#ec4899','#f59e0b','#10b981','#ef4444','#06b6d4'];
const COL_W = 180, ROW_H = 48, PAD_X = 20, PAD_Y = 44;

export default function DependencyGraphChart({ projectName }: { projectName?: string }) {
  const [data, setData] = useState<GraphData | null>(null);
  const [sel, setSel] = useState<Sel>(null);

  useEffect(() => {
    const qs = projectName ? `?name=${encodeURIComponent(projectName)}` : '';
    fetch(`/api/dashboard/cross-project-dependency-graph${qs}`)
      .then(r => r.json() as Promise<GraphData>)
      .then(setData)
      .catch(() => setData({ sub_projects: [], nodes: [], edges: [] }));
  }, [projectName]);

  if (!data) return <div className="p-6 text-slate-400 text-sm">Loading\u2026</div>;
  if (!data.nodes.length) return <div className="p-6 text-slate-400 text-sm">No cross-project stories found.</div>;

  const colorOf = (p: string): string => COLORS[data.sub_projects.indexOf(p) % COLORS.length] ?? '#94a3b8';
  const nodesByProj: Record<string, GNode[]> = {};
  for (const p of data.sub_projects) nodesByProj[p] = data.nodes.filter(n => n.sub_project === p);
  const maxRows = Math.max(...Object.values(nodesByProj).map(ns => ns.length), 1);
  const svgW = Math.max(data.sub_projects.length * COL_W + 2 * PAD_X, 400);
  const svgH = maxRows * ROW_H + 2 * PAD_Y + 20;

  const pos: Record<string, { x: number; y: number }> = {};
  data.sub_projects.forEach((p, ci) => {
    (nodesByProj[p] ?? []).forEach((n, ri) => {
      pos[n.id] = { x: PAD_X + ci * COL_W + COL_W / 2, y: PAD_Y + 20 + ri * ROW_H };
    });
  });

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 pt-3 pb-1 flex flex-wrap gap-3 text-xs text-slate-600 flex-shrink-0">
        {data.sub_projects.map(p => (
          <span key={p} className="flex items-center gap-1.5">
            <span className="w-3 h-3 rounded-sm inline-block" style={{ background: colorOf(p) }} />{p}
          </span>
        ))}
      </div>
      <div className="flex-1 overflow-auto">
        <svg width={svgW} height={svgH}>
          <defs>
            <marker id="dgc-arr" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
              <path d="M0,0 L7,3.5 L0,7 Z" fill="#94a3b8" />
            </marker>
          </defs>
          {data.sub_projects.map((p, ci) => (
            <text key={p} x={PAD_X + ci * COL_W + COL_W / 2} y={PAD_Y - 4} textAnchor="middle"
              fill={colorOf(p)} fontSize={12} fontWeight="bold">{p}</text>
          ))}
          {data.edges.map((e, i) => {
            const s = pos[e.from], t = pos[e.to];
            if (!s || !t) return null;
            return (
              <g key={i} onClick={() => setSel({ type: 'edge', data: e })} style={{ cursor: 'pointer' }}>
                <line x1={s.x} y1={s.y} x2={t.x} y2={t.y} stroke="#94a3b8" strokeWidth={1.5} markerEnd="url(#dgc-arr)" />
                <line x1={s.x} y1={s.y} x2={t.x} y2={t.y} stroke="transparent" strokeWidth={12} />
              </g>
            );
          })}
          {data.nodes.map(n => {
            const p = pos[n.id];
            if (!p) return null;
            const c = colorOf(n.sub_project);
            return (
              <g key={n.id} onClick={() => setSel({ type: 'node', data: n })} style={{ cursor: 'pointer' }}>
                <rect x={p.x - 52} y={p.y - 11} width={104} height={22} rx={4}
                  fill={n.passes ? c : '#f8fafc'} stroke={c} strokeWidth={1.5} />
                <text x={p.x} y={p.y + 4} textAnchor="middle" fontSize={10}
                  fill={n.passes ? '#fff' : '#334155'}>{n.id}</text>
              </g>
            );
          })}
        </svg>
      </div>
      {sel !== null && (
        <div className="border-t border-slate-200 bg-white px-4 py-3 flex-shrink-0 text-sm">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              {sel.type === 'node' ? (
                <>
                  <div className="font-semibold text-slate-800">{sel.data.id}</div>
                  <div className="text-slate-500 mt-0.5 truncate">{sel.data.title}</div>
                  <div className="mt-1 flex items-center gap-2">
                    <span className="text-[10px] text-white px-1.5 py-0.5 rounded" style={{ background: colorOf(sel.data.sub_project) }}>{sel.data.sub_project}</span>
                    <span className={`text-[10px] ${sel.data.passes ? 'text-emerald-600' : 'text-amber-600'}`}>{sel.data.passes ? '\u2713 Passed' : '\u25cb Pending'}</span>
                  </div>
                </>
              ) : (
                <>
                  <div className="font-semibold text-slate-800">Blockage: {sel.data.reason}</div>
                  <div className="text-slate-500 text-xs mt-0.5">{sel.data.from_project} \u2192 {sel.data.to_project}</div>
                </>
              )}
            </div>
            <button onClick={() => setSel(null)} className="text-slate-400 hover:text-slate-600 flex-shrink-0 text-base leading-none">\u2715</button>
          </div>
        </div>
      )}
    </div>
  );
}
