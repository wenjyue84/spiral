import { useState } from 'react';
import { CONFIG_FIELDS, CATEGORIES, type ConfigField } from '../data/configSchema';
import { ZONE_COLORS } from '../data/phases';

// ── Types ──────────────────────────────────────────────────────────────────────

export type ConfigValues = Record<string, string | number | boolean>;

interface SettingsPanelProps {
  values: ConfigValues;
  onChange: (key: string, value: string | number | boolean) => void;
}

// ── Phase badge label map ──────────────────────────────────────────────────────

const PHASE_ZONE: Record<string, keyof typeof ZONE_COLORS> = {
  A: 'pipeline', R: 'pipeline', T: 'pipeline',
  S: 'pipeline', M: 'pipeline',
  G: 'decision',
  I: 'implement',
  V: 'validate',
};

function PhaseBadge({ phase }: { phase: string }) {
  const zone = PHASE_ZONE[phase] ?? 'pipeline';
  const colors = ZONE_COLORS[zone];
  return (
    <span
      className="inline-block text-[10px] font-bold px-1.5 py-0.5 rounded ml-1 leading-tight"
      style={{ background: colors.border, color: '#fff' }}
    >
      {phase}
    </span>
  );
}

// ── Field renderers ────────────────────────────────────────────────────────────

function FieldControl({ field, value, onChange }: {
  field: ConfigField;
  value: string | number | boolean;
  onChange: (v: string | number | boolean) => void;
}) {
  const base = 'w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400';

  if (field.type === 'toggle') {
    return (
      <button
        type="button"
        onClick={() => onChange(!value)}
        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${value ? 'bg-blue-600' : 'bg-slate-300'}`}
      >
        <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${value ? 'translate-x-6' : 'translate-x-1'}`} />
      </button>
    );
  }

  if (field.type === 'select') {
    return (
      <select
        className={base}
        value={String(value)}
        onChange={e => onChange(e.target.value)}
      >
        {field.options!.map(opt => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
    );
  }

  if (field.type === 'number') {
    return (
      <input
        type="number"
        className={base}
        value={String(value)}
        placeholder={field.placeholder}
        onChange={e => onChange(e.target.value === '' ? 0 : Number(e.target.value))}
      />
    );
  }

  // text
  return (
    <input
      type="text"
      className={base}
      value={String(value)}
      placeholder={field.placeholder}
      onChange={e => onChange(e.target.value)}
    />
  );
}

// ── Category section ───────────────────────────────────────────────────────────

function CategorySection({ category, fields, values, onChange }: {
  category: string;
  fields: ConfigField[];
  values: ConfigValues;
  onChange: (key: string, value: string | number | boolean) => void;
}) {
  const [open, setOpen] = useState(true);

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 bg-slate-50 hover:bg-slate-100 transition-colors text-left"
      >
        <span className="font-semibold text-slate-800 text-sm">{category}</span>
        <span className="text-slate-400 text-xs select-none">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="divide-y divide-slate-100">
          {fields.map(field => (
            <div key={field.key} className="px-4 py-3 grid grid-cols-1 sm:grid-cols-[1fr_220px] gap-3 items-start">
              <div>
                <div className="flex items-center gap-1 flex-wrap">
                  <label className="text-sm font-medium text-slate-700">{field.label}</label>
                  {field.phase && <PhaseBadge phase={field.phase} />}
                </div>
                <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">{field.description}</p>
                <code className="text-[10px] text-slate-400">{field.key}</code>
              </div>
              <div className="flex items-center">
                <FieldControl field={field} value={values[field.key] ?? field.defaultValue} onChange={v => onChange(field.key, v)} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function SettingsPanel({ values, onChange }: SettingsPanelProps) {
  return (
    <div className="flex flex-col gap-4">
      {CATEGORIES.map(cat => (
        <CategorySection
          key={cat}
          category={cat}
          fields={CONFIG_FIELDS.filter(f => f.category === cat)}
          values={values}
          onChange={onChange}
        />
      ))}
    </div>
  );
}

export function defaultValues(): ConfigValues {
  return Object.fromEntries(CONFIG_FIELDS.map(f => [f.key, f.defaultValue]));
}
