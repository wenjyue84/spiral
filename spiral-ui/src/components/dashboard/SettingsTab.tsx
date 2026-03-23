import { useState, useEffect } from 'react';
import { CONFIG_FIELDS } from '../data/configSchema';

/** Update key=value lines in raw config content, preserving comments. */
function buildUpdatedConfig(rawContent: string, updates: Record<string, string>): string {
  const handled = new Set<string>();
  const result = rawContent.split('\n').map(line => {
    const m = line.match(/^(\s*(?:export\s+)?)([A-Z_][A-Z0-9_]*)=(["']?)([^#\n]*?)\3(\s*#.*)?$/);
    if (m) {
      const key = m[2];
      if (key in updates) {
        handled.add(key);
        const val = updates[key].replace(/"/g, '\\"');
        return `${m[1]}${key}="${val}"${m[5] ? '  ' + m[5].trim() : ''}`;
      }
    }
    return line;
  });
  const newKeys = Object.entries(updates).filter(([k]) => !handled.has(k));
  if (newKeys.length > 0) {
    result.push('');
    result.push('# Added via SPIRAL UI');
    for (const [k, v] of newKeys) result.push(`export ${k}="${v.replace(/"/g, '\\"')}"`);
  }
  return result.join('\n');
}

export default function SettingsTab({ config, configRaw, projectName, onConfigSaved }: {
  config: Record<string, string>;
  configRaw: string;
  projectName: string;
  onConfigSaved?: () => void;
}) {
  const [edited, setEdited] = useState<Record<string, string>>(() => ({ ...config }));
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ ok: boolean; text: string } | null>(null);

  // Reset edited state when config changes (e.g. after save + refresh)
  useEffect(() => { setEdited({ ...config }); }, [JSON.stringify(config)]); // eslint-disable-line

  const knownKeys = new Set(CONFIG_FIELDS.map(f => f.key));
  const unknownKeys = Object.keys(config).filter(k => !knownKeys.has(k));

  // All rows: known CONFIG_FIELDS that exist in config, plus unknown raw keys
  const rows = [
    ...CONFIG_FIELDS.filter(f => f.key in config),
    ...unknownKeys.map(k => ({ key: k, label: k, description: '', type: 'text' as const, options: undefined })),
  ];

  const handleSave = async () => {
    setSaving(true);
    setSaveMsg(null);
    try {
      const newContent = buildUpdatedConfig(configRaw, edited);
      const res = await fetch('/api/save-config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: newContent, name: projectName }),
      });
      const d = await res.json() as { ok?: boolean; error?: string };
      if (d.ok) { setSaveMsg({ ok: true, text: 'Saved!' }); onConfigSaved?.(); }
      else setSaveMsg({ ok: false, text: d.error ?? 'Save failed' });
    } catch (e) {
      setSaveMsg({ ok: false, text: String(e) });
    } finally { setSaving(false); }
  };

  if (rows.length === 0) {
    return <div className="p-6 text-slate-500">No spiral.config.sh found for this project.</div>;
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-700">spiral.config.sh</h3>
          <p className="text-xs text-slate-400 mt-0.5">Edit values and click Save to write to disk.</p>
        </div>
        <div className="flex items-center gap-3">
          {saveMsg && (
            <span className={`text-xs font-medium ${saveMsg.ok ? 'text-emerald-600' : 'text-red-600'}`}>{saveMsg.text}</span>
          )}
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-1.5 bg-blue-600 text-white text-xs font-semibold rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save Config'}
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-slate-50 text-slate-500">
            <tr>
              <th className="px-4 py-2.5 text-left font-medium w-2/5">Variable</th>
              <th className="px-4 py-2.5 text-left font-medium">Value</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(f => {
              const val = edited[f.key] ?? '';
              return (
                <tr key={f.key} className="border-t border-slate-100 hover:bg-slate-50">
                  <td className="px-4 py-2.5 align-top">
                    <div className="font-mono text-blue-700 whitespace-nowrap">{f.key}</div>
                    {f.label !== f.key && <div className="text-[10px] text-slate-400 mt-0.5">{f.label}</div>}
                    {f.description && (
                      <div className="text-[10px] text-slate-400 mt-0.5 max-w-xs leading-tight">
                        {f.description.length > 100 ? f.description.slice(0, 100) + '…' : f.description}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-2 align-middle">
                    {f.type === 'select' && f.options ? (
                      <select
                        className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-400"
                        value={val}
                        onChange={e => setEdited(p => ({ ...p, [f.key]: e.target.value }))}
                      >
                        {f.options.map(opt => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
                      </select>
                    ) : f.type === 'toggle' ? (
                      <button
                        type="button"
                        onClick={() => setEdited(p => ({ ...p, [f.key]: val === 'true' ? 'false' : 'true' }))}
                        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${val === 'true' ? 'bg-blue-600' : 'bg-slate-300'}`}
                      >
                        <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${val === 'true' ? 'translate-x-6' : 'translate-x-1'}`} />
                      </button>
                    ) : (
                      <input
                        type={f.type === 'number' ? 'number' : 'text'}
                        className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-blue-400"
                        value={val}
                        onChange={e => setEdited(p => ({ ...p, [f.key]: e.target.value }))}
                      />
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
