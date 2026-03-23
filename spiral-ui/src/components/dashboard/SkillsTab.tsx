import { useState, useEffect } from 'react';

export default function SkillsTab({ projectName }: { projectName?: string }) {
  const [skills, setSkills] = useState<{ name: string }[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [content, setContent] = useState('');
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');
  const [loadingSkill, setLoadingSkill] = useState(false);

  useEffect(() => {
    const qs = projectName ? `?name=${encodeURIComponent(projectName)}` : '';
    fetch(`/api/skills${qs}`)
      .then(r => r.json() as Promise<{ skills: { name: string }[] }>)
      .then(d => {
        setSkills(d.skills ?? []);
        if (d.skills?.length && !selected) setSelected(d.skills[0].name);
      })
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectName]);

  useEffect(() => {
    if (!selected) return;
    setLoadingSkill(true);
    setError('');
    const qs = projectName ? `&name=${encodeURIComponent(projectName)}` : '';
    fetch(`/api/skill?skill=${encodeURIComponent(selected)}${qs}`)
      .then(r => r.json() as Promise<{ content?: string; error?: string }>)
      .then(d => {
        if (d.error) { setError(d.error); return; }
        setContent(d.content ?? '');
        setDraft(d.content ?? '');
      })
      .catch(e => setError(String(e)))
      .finally(() => setLoadingSkill(false));
  }, [selected, projectName]);

  async function handleSave() {
    if (!selected) return;
    setSaving(true);
    setError('');
    try {
      const res = await fetch('/api/save-skill', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: draft, skillName: selected, name: projectName }),
      });
      const data = await res.json() as { ok?: boolean; error?: string };
      if (!data.ok) throw new Error(data.error ?? 'Save failed');
      setContent(draft);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  const lineCount = draft.split('\n').length;
  const isDirty = draft !== content;

  return (
    <div className="flex h-full">
      <div className="w-48 shrink-0 border-r border-slate-200 bg-slate-50 flex flex-col">
        <div className="px-3 py-2 text-xs font-semibold text-slate-500 uppercase tracking-wide border-b border-slate-200">
          Skills
        </div>
        <div className="flex-1 overflow-y-auto py-1">
          {skills.length === 0 && (
            <div className="px-3 py-3 text-xs text-slate-400 italic">No skills found in ralph/skills/</div>
          )}
          {skills.map(s => (
            <button
              key={s.name}
              onClick={() => { setSelected(s.name); setError(''); }}
              className={`w-full text-left px-3 py-2 text-xs font-mono truncate transition-colors ${
                selected === s.name
                  ? 'bg-blue-50 text-blue-700 font-semibold border-r-2 border-blue-600'
                  : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              {s.name}
            </button>
          ))}
        </div>
      </div>
      <div className="flex-1 flex flex-col overflow-hidden">
        {!selected ? (
          <div className="p-6 text-slate-500 text-sm">Select a skill from the sidebar.</div>
        ) : loadingSkill ? (
          <div className="p-6 text-slate-400 text-sm">Loading…</div>
        ) : (
          <div className="p-6 flex flex-col gap-3 h-full">
            <div className="flex items-center gap-3">
              <span className="text-xs font-mono text-slate-500">{selected}.md</span>
              <span className="text-xs text-slate-400">·</span>
              <span className="text-xs text-slate-500 font-mono">{lineCount} lines</span>
              <div className="ml-auto flex items-center gap-2">
                {error && <span className="text-xs text-red-600">{error}</span>}
                {saved && <span className="text-xs text-green-600 font-medium">✓ Saved</span>}
                <button
                  onClick={handleSave}
                  disabled={saving || !isDirty}
                  className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
                    isDirty
                      ? 'bg-blue-600 hover:bg-blue-700 text-white'
                      : 'bg-slate-100 text-slate-400 cursor-not-allowed'
                  }`}
                >
                  {saving ? 'Saving…' : 'Save'}
                </button>
              </div>
            </div>
            <textarea
              value={draft}
              onChange={e => setDraft(e.target.value)}
              className="flex-1 w-full rounded-xl border border-slate-200 bg-white p-5 text-xs text-slate-700 font-mono leading-relaxed resize-none focus:outline-none focus:ring-2 focus:ring-blue-300"
              spellCheck={false}
              style={{ minHeight: '400px' }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
