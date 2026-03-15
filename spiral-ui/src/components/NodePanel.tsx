import { CONFIG_FIELDS, type ConfigField } from '../data/configSchema';
import { PHASES, ZONE_COLORS } from '../data/phases';
import type { ConfigValues } from './SettingsPanel';

// ── Inline field control (compact for the panel) ───────────────────────────────

function FieldRow({ field, value, onChange }: {
  field: ConfigField;
  value: string | number | boolean;
  onChange: (v: string | number | boolean) => void;
}) {
  const base = 'w-full rounded border border-slate-300 bg-white px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-blue-400';

  return (
    <div className="py-2.5 border-b border-slate-100 last:border-0">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="text-xs font-medium text-slate-700 leading-tight">{field.label}</div>
          <div className="text-[10px] text-slate-400 mt-0.5 leading-snug">{field.description}</div>
        </div>
      </div>
      <div className="mt-1.5">
        {field.type === 'toggle' && (
          <button
            type="button"
            onClick={() => onChange(!value)}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${value ? 'bg-blue-600' : 'bg-slate-300'}`}
          >
            <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${value ? 'translate-x-4' : 'translate-x-0.5'}`} />
          </button>
        )}
        {field.type === 'select' && (
          <select className={base} value={String(value)} onChange={e => onChange(e.target.value)}>
            {field.options!.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        )}
        {field.type === 'number' && (
          <input type="number" className={base} value={String(value)} placeholder={field.placeholder}
            onChange={e => onChange(e.target.value === '' ? 0 : Number(e.target.value))} />
        )}
        {field.type === 'text' && (
          <input type="text" className={base} value={String(value)} placeholder={field.placeholder}
            onChange={e => onChange(e.target.value)} />
        )}
      </div>
    </div>
  );
}

// ── Ralph node info ────────────────────────────────────────────────────────────

const RALPH_INFO: Record<string, { label: string; detail: string }> = {
  R1: { label: 'Pick Story', detail: 'Selects the next story by priority score and dependency order from prd.json.' },
  R2: { label: 'Create Branch', detail: 'Creates a git feature branch and optional worktree for isolated implementation.' },
  R3: { label: 'Claude Implements', detail: 'Claude agent (haiku/sonnet/opus) decomposes and executes the story.' },
  R4: { label: 'Tests Pass?', detail: 'Runs SPIRAL_VALIDATE_CMD. Passes → commit. Fails → revert + escalate model.' },
  R5: { label: 'Commit', detail: 'Marks the story as passes:true in prd.json and commits the branch.' },
  R6: { label: 'Revert + Escalate', detail: 'Reverts changes and retries with a more capable model (haiku → sonnet → opus).' },
};

// ── Main component ─────────────────────────────────────────────────────────────

interface NodePanelProps {
  nodeId: string;
  nodeLabel: string;
  nodeSub?: string;
  nodeZone?: string;
  values: ConfigValues;
  onChange: (key: string, value: string | number | boolean) => void;
  onClose: () => void;
}

export default function NodePanel({ nodeId, nodeLabel, nodeSub, nodeZone, values, onChange, onClose }: NodePanelProps) {
  const phase = PHASES.find(p => p.id === nodeId);
  const phaseFields = CONFIG_FIELDS.filter(f => f.phase === nodeId);
  const ralphInfo = RALPH_INFO[nodeId];

  // Implementation phase settings also apply to Ralph sub-nodes
  const implFields = (nodeId.startsWith('R') && nodeId !== 'R') ? CONFIG_FIELDS.filter(f => f.phase === 'I') : [];
  const shownFields = phaseFields.length > 0 ? phaseFields : implFields;

  const zone = (nodeZone ?? 'pipeline') as keyof typeof ZONE_COLORS;
  const colors = ZONE_COLORS[zone] ?? ZONE_COLORS.pipeline;

  return (
    <div className="flex flex-col h-full bg-white shadow-2xl border-l border-slate-200 overflow-hidden">
      {/* Header */}
      <div className="flex items-start justify-between px-4 pt-4 pb-3 flex-shrink-0"
        style={{ background: colors.bg, borderBottom: `2px solid ${colors.border}` }}>
        <div>
          <div className="text-sm font-bold leading-tight" style={{ color: colors.text }}>{nodeLabel}</div>
          {nodeSub && <div className="text-xs mt-0.5 opacity-75 leading-snug" style={{ color: colors.text }}>{nodeSub}</div>}
        </div>
        <button onClick={onClose}
          className="ml-2 p-1 rounded hover:bg-black/10 text-slate-600 transition-colors flex-shrink-0 text-base leading-none"
          aria-label="Close">✕</button>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto px-4 py-3 text-xs">

        {/* Phase metadata */}
        {phase && (
          <div className="mb-3 space-y-2">
            {phase.script && (
              <div>
                <div className="font-semibold text-slate-500 uppercase tracking-wide text-[10px] mb-0.5">Script</div>
                <code className="text-slate-700 break-all">{phase.script}</code>
              </div>
            )}
            {phase.inputs.length > 0 && (
              <div>
                <div className="font-semibold text-slate-500 uppercase tracking-wide text-[10px] mb-0.5">Inputs</div>
                <div className="flex flex-wrap gap-1">
                  {phase.inputs.map(i => (
                    <span key={i} className="bg-slate-100 text-slate-700 rounded px-1.5 py-0.5">{i}</span>
                  ))}
                </div>
              </div>
            )}
            {phase.outputs.length > 0 && (
              <div>
                <div className="font-semibold text-slate-500 uppercase tracking-wide text-[10px] mb-0.5">Outputs</div>
                <div className="flex flex-wrap gap-1">
                  {phase.outputs.map(o => (
                    <span key={o} className="bg-emerald-50 text-emerald-700 border border-emerald-200 rounded px-1.5 py-0.5">{o}</span>
                  ))}
                </div>
              </div>
            )}
            {phase.skipCondition && (
              <div>
                <div className="font-semibold text-slate-500 uppercase tracking-wide text-[10px] mb-0.5">Skip when</div>
                <div className="text-amber-700 italic">{phase.skipCondition}</div>
              </div>
            )}
          </div>
        )}

        {/* Ralph node info */}
        {ralphInfo && (
          <div className="mb-3 bg-pink-50 border border-pink-200 rounded p-2.5">
            <div className="font-semibold text-pink-800 mb-0.5">{ralphInfo.label}</div>
            <div className="text-pink-700 leading-snug">{ralphInfo.detail}</div>
            <div className="mt-1.5 text-[10px] text-pink-500">Part of Phase I — Implementation loop</div>
          </div>
        )}

        {/* Terminal nodes */}
        {(nodeId === 'DONE' || nodeId === 'EXIT') && (
          <div className="text-slate-500 italic">
            {nodeId === 'DONE' ? 'All stories completed. All tests pass. SPIRAL loop exits successfully.' : 'User chose to quit at the Gate checkpoint.'}
          </div>
        )}

        {/* Config settings */}
        {shownFields.length > 0 && (
          <>
            <div className="font-semibold text-slate-500 uppercase tracking-wide text-[10px] mb-1 mt-1">
              {implFields.length > 0 && phaseFields.length === 0 ? 'Phase I Settings' : 'Settings'}
            </div>
            {shownFields.map(field => (
              <FieldRow
                key={field.key}
                field={field}
                value={values[field.key] ?? field.defaultValue}
                onChange={v => onChange(field.key, v)}
              />
            ))}
          </>
        )}

        {/* No settings */}
        {shownFields.length === 0 && !ralphInfo && nodeId !== 'DONE' && nodeId !== 'EXIT' && (
          <div className="text-slate-400 italic text-[11px]">No configurable settings for this phase.</div>
        )}
      </div>
    </div>
  );
}
