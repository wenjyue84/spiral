import { useState, useEffect } from 'react';
import { Routes, Route, useNavigate } from 'react-router-dom';
import WorkflowDiagram from './components/WorkflowDiagram';
import SettingsPanel, { defaultValues, type ConfigValues } from './components/SettingsPanel';
import ConfigGenerator from './components/ConfigGenerator';
import NodePanel from './components/NodePanel';
import ProjectDashboard from './components/ProjectDashboard';
import CostAnalysisTab from './components/CostAnalysisTab';

type Tab = 'projects' | 'workflow' | 'settings' | 'config';

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: 'projects', label: 'Projects', icon: '🗂' },
  { id: 'workflow', label: 'Workflow', icon: '⬡' },
  { id: 'settings', label: 'Settings', icon: '⚙' },
  { id: 'config',   label: 'Config Output', icon: '📄' },
];

// ── Projects tab ─────────────────────────────────────────────────────────────

interface ProjectEntry { name: string; root: string }
interface ProjectLive {
  progress?: { done: number; pending: number; total: number };
  config?: Record<string, string>;
}

function ProjectsTab() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<ProjectEntry[]>([]);
  const [live, setLive] = useState<Record<string, ProjectLive>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/projects')
      .then(r => r.json())
      .then((data: { projects: ProjectEntry[] }) => {
        setProjects(data.projects ?? []);
        setLoading(false);
        // Fetch live stats for each project in parallel
        data.projects.forEach(p => {
          fetch(`/api/project-live?name=${encodeURIComponent(p.name)}`)
            .then(r => r.json())
            .then((liveData: ProjectLive) => {
              setLive(prev => ({ ...prev, [p.name]: liveData }));
            })
            .catch(() => {/* ignore */});
        });
      })
      .catch(() => setLoading(false));
  }, []);

  // Compute summary stats across all projects
  const summary = Object.values(live).reduce(
    (acc, l) => {
      if (l.progress) {
        acc.done += l.progress.done;
        acc.pending += l.progress.pending;
        acc.total += l.progress.total;
      }
      return acc;
    },
    { done: 0, pending: 0, total: 0 },
  );
  const hasStats = summary.total > 0;

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400 text-sm">
        Loading projects…
      </div>
    );
  }

  if (projects.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 text-slate-500 max-w-md mx-auto text-center px-4">
        <span className="text-5xl">📭</span>
        <div>
          <p className="text-base font-medium text-slate-700 mb-1">No projects registered yet</p>
          <p className="text-sm text-slate-400">Get started by running SPIRAL on any project directory:</p>
        </div>
        <div className="bg-slate-50 border border-slate-200 rounded-lg p-4 w-full text-left space-y-3">
          <div>
            <p className="text-xs font-semibold text-slate-500 mb-1">Option 1 — Run SPIRAL</p>
            <code className="text-xs bg-white px-2 py-1 rounded border border-slate-200 block text-slate-700">
              bash spiral.sh 5 --gate proceed
            </code>
          </div>
          <div>
            <p className="text-xs font-semibold text-slate-500 mb-1">Option 2 — Register manually</p>
            <code className="text-xs bg-white px-2 py-1 rounded border border-slate-200 block text-slate-700 break-all">
              curl -X POST localhost:5299/api/register-project -H "Content-Type: application/json" -d '{`{"name":"MyProject","root":"/path/to/project"}`}'
            </code>
          </div>
        </div>
        <p className="text-xs text-slate-400">
          Switch to the <span className="font-medium">Workflow</span> tab to explore the SPIRAL phase loop.
        </p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto px-6 py-5">
      <div className="max-w-5xl mx-auto">
        <div className="mb-5 flex items-end justify-between gap-4 flex-wrap">
          <div>
            <h2 className="text-lg font-semibold text-slate-800">Active Projects</h2>
            <p className="text-sm text-slate-500 mt-0.5">{projects.length} project{projects.length !== 1 ? 's' : ''} registered — click to open dashboard</p>
          </div>
          {hasStats && (
            <div className="flex gap-4 text-xs font-medium">
              <span className="bg-green-50 text-green-700 px-2.5 py-1 rounded-full">{summary.done} done</span>
              <span className="bg-amber-50 text-amber-700 px-2.5 py-1 rounded-full">{summary.pending} pending</span>
              <span className="bg-slate-50 text-slate-500 px-2.5 py-1 rounded-full">{summary.total} total stories</span>
            </div>
          )}
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {projects.map(p => {
            const stats = live[p.name]?.progress;
            const pct = stats && stats.total > 0 ? Math.round((stats.done / stats.total) * 100) : null;
            return (
              <button
                key={p.name}
                onClick={() => navigate(`/${encodeURIComponent(p.name)}`)}
                className="text-left bg-white rounded-xl border border-slate-200 p-4 shadow-sm hover:shadow-md hover:border-blue-300 transition-all group"
              >
                <div className="flex items-start justify-between gap-2 mb-3">
                  <span className="font-semibold text-slate-800 group-hover:text-blue-700 transition-colors leading-tight">
                    {p.name}
                  </span>
                  {pct !== null && (
                    <span className={`text-xs font-bold px-2 py-0.5 rounded-full flex-shrink-0 ${
                      pct === 100 ? 'bg-green-100 text-green-700' :
                      pct >= 50   ? 'bg-blue-100 text-blue-700' :
                                    'bg-slate-100 text-slate-500'
                    }`}>
                      {pct}%
                    </span>
                  )}
                </div>

                {stats ? (
                  <>
                    <div className="w-full bg-slate-100 rounded-full h-1.5 mb-2">
                      <div
                        className={`h-1.5 rounded-full transition-all ${pct === 100 ? 'bg-green-500' : 'bg-blue-500'}`}
                        style={{ width: `${pct ?? 0}%` }}
                      />
                    </div>
                    <div className="flex gap-3 text-xs text-slate-500">
                      <span>✅ {stats.done} done</span>
                      <span>⏳ {stats.pending} pending</span>
                      <span className="text-slate-300">/ {stats.total} total</span>
                    </div>
                  </>
                ) : (
                  <div className="text-xs text-slate-400 italic">Loading stats…</div>
                )}

                <div className="mt-3 text-xs text-slate-300 truncate" title={p.root}>
                  {p.root}
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

interface SelectedNode {
  id: string;
  label: string;
  sub: string;
  zone: string;
}

type SpiralStatus = 'idle' | 'running' | 'unknown';

function useSystemStatus(): SpiralStatus {
  const [status, setStatus] = useState<SpiralStatus>('unknown');
  useEffect(() => {
    fetch('/api/workers-status')
      .then(r => r.json())
      .then((data: { workers?: unknown[] }) => {
        setStatus(data.workers && data.workers.length > 0 ? 'running' : 'idle');
      })
      .catch(() => setStatus('idle'));
  }, []);
  return status;
}

function SpiralHome() {
  const [activeTab, setActiveTab] = useState<Tab>('projects');
  const [values, setValues] = useState<ConfigValues>(defaultValues());
  const [selectedNode, setSelectedNode] = useState<SelectedNode | null>(null);
  const systemStatus = useSystemStatus();

  const handleChange = (key: string, value: string | number | boolean) => {
    setValues(prev => ({ ...prev, [key]: value }));
  };

  const handleNodeSelect = (id: string | null, label: string, sub: string, zone: string) => {
    setSelectedNode(id ? { id, label, sub, zone } : null);
  };

  return (
    <div className="flex flex-col h-screen bg-slate-100 overflow-hidden">
      {/* ── Top bar ─────────────────────────────────────────────────────────── */}
      <header className="flex items-center gap-4 px-5 py-2.5 bg-white border-b border-slate-200 shadow-sm flex-shrink-0">
        <div className="flex items-center gap-2.5">
          <span className="text-xl font-bold text-blue-700 tracking-tight">SPIRAL</span>
          <span className="text-xs text-slate-400 font-medium">Autonomous Dev Loop</span>
          {systemStatus !== 'unknown' && (
            <span className={`ml-1 flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${
              systemStatus === 'running'
                ? 'bg-green-100 text-green-700'
                : 'bg-slate-100 text-slate-500'
            }`}>
              <span className={`inline-block w-1.5 h-1.5 rounded-full ${
                systemStatus === 'running' ? 'bg-green-500 animate-pulse' : 'bg-slate-400'
              }`} />
              {systemStatus === 'running' ? 'Running' : 'Idle'}
            </span>
          )}
        </div>

        <nav className="flex gap-1 ml-4">
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`
                flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors
                ${activeTab === tab.id
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'text-slate-600 hover:bg-slate-100'}
              `}
            >
              <span>{tab.icon}</span>
              {tab.label}
            </button>
          ))}
        </nav>

        {/* Workflow legend */}
        {activeTab === 'workflow' && (
          <div className="ml-auto flex items-center gap-3 flex-wrap">
            {selectedNode ? (
              <span className="text-xs text-slate-500 italic">
                Click canvas to deselect
              </span>
            ) : (
              <span className="text-xs text-slate-400 italic">Click a node to configure it</span>
            )}
            {[
              { label: 'Startup',   bg: '#16a34a' },
              { label: 'Pipeline',  bg: '#2563eb' },
              { label: 'Implement', bg: '#ea580c' },
              { label: 'Validate',  bg: '#7c3aed' },
              { label: 'Decision',  bg: '#ca8a04' },
            ].map(z => (
              <span key={z.label} className="flex items-center gap-1 text-xs text-slate-600">
                <span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ background: z.bg }} />
                {z.label}
              </span>
            ))}
          </div>
        )}
      </header>

      {/* ── Main content ────────────────────────────────────────────────────── */}
      <main className="flex-1 overflow-hidden">

        {/* Projects tab */}
        {activeTab === 'projects' && <ProjectsTab />}

        {/* Workflow tab — diagram + slide-in panel */}
        {activeTab === 'workflow' && (
          <div className="flex h-full">
            {/* Diagram */}
            <div className="flex-1 min-w-0 h-full">
              <WorkflowDiagram
                selectedNodeId={selectedNode?.id ?? null}
                onNodeSelect={handleNodeSelect}
              />
            </div>

            {/* Settings panel — slides in from right */}
            {selectedNode && (
              <div
                className="w-80 flex-shrink-0 h-full overflow-hidden border-l border-slate-200"
                style={{ animation: 'slideIn 0.18s ease-out' }}
              >
                <NodePanel
                  nodeId={selectedNode.id}
                  nodeLabel={selectedNode.label}
                  nodeSub={selectedNode.sub}
                  nodeZone={selectedNode.zone}
                  values={values}
                  onChange={handleChange}
                  onClose={() => setSelectedNode(null)}
                />
              </div>
            )}
          </div>
        )}

        {/* Settings tab — scrollable form */}
        {activeTab === 'settings' && (
          <div className="h-full overflow-y-auto px-6 py-5">
            <div className="max-w-3xl mx-auto">
              <div className="mb-5">
                <h2 className="text-lg font-semibold text-slate-800">SPIRAL Configuration</h2>
                <p className="text-sm text-slate-500 mt-0.5">
                  Adjust settings below. Switch to Config Output to generate{' '}
                  <code className="bg-slate-100 px-1 rounded text-xs">spiral.config.sh</code>.
                </p>
              </div>
              <SettingsPanel values={values} onChange={handleChange} />
            </div>
          </div>
        )}

        {/* Config output tab */}
        {activeTab === 'config' && (
          <div className="h-full overflow-hidden px-6 py-5">
            <div className="max-w-3xl mx-auto h-full flex flex-col">
              <div className="mb-4">
                <h2 className="text-lg font-semibold text-slate-800">Config Output</h2>
                <p className="text-sm text-slate-500 mt-0.5">
                  Reflects all settings from the Settings tab. Download and source before running SPIRAL.
                </p>
              </div>
              <div className="flex-1 min-h-0">
                <ConfigGenerator values={values} />
              </div>
            </div>
          </div>
        )}
      </main>

      {/* Slide-in animation */}
      <style>{`
        @keyframes slideIn {
          from { transform: translateX(100%); opacity: 0; }
          to   { transform: translateX(0);    opacity: 1; }
        }
      `}</style>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<SpiralHome />} />
      <Route path="/:projectName" element={<ProjectDashboard />} />
      <Route path="/:projectName/:tab" element={<ProjectDashboard />} />
    </Routes>
  );
}
