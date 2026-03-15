import { useState } from 'react';
import WorkflowDiagram from './components/WorkflowDiagram';
import SettingsPanel, { defaultValues, type ConfigValues } from './components/SettingsPanel';
import ConfigGenerator from './components/ConfigGenerator';

type Tab = 'workflow' | 'settings' | 'config';

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: 'workflow', label: 'Workflow', icon: '⬡' },
  { id: 'settings', label: 'Settings', icon: '⚙' },
  { id: 'config',   label: 'Config Output', icon: '📄' },
];

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>('workflow');
  const [values, setValues] = useState<ConfigValues>(defaultValues());

  const handleChange = (key: string, value: string | number | boolean) => {
    setValues(prev => ({ ...prev, [key]: value }));
  };

  return (
    <div className="flex flex-col h-screen bg-slate-100 overflow-hidden">
      {/* ── Top bar ─────────────────────────────────────────────────────────── */}
      <header className="flex items-center gap-4 px-5 py-2.5 bg-white border-b border-slate-200 shadow-sm flex-shrink-0">
        <div className="flex items-center gap-2.5">
          <span className="text-xl font-bold text-blue-700 tracking-tight">SPIRAL</span>
          <span className="text-xs text-slate-400 font-medium">Autonomous Dev Loop</span>
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

        {/* Legend */}
        {activeTab === 'workflow' && (
          <div className="ml-auto flex gap-2 flex-wrap">
            {[
              { label: 'Startup', bg: '#16a34a' },
              { label: 'Pipeline', bg: '#2563eb' },
              { label: 'Implement', bg: '#ea580c' },
              { label: 'Validate', bg: '#7c3aed' },
              { label: 'Decision', bg: '#ca8a04' },
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
        {/* Workflow tab — full bleed React Flow */}
        {activeTab === 'workflow' && (
          <div className="w-full h-full">
            <WorkflowDiagram />
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
    </div>
  );
}
