import { useState, useEffect } from 'react';

interface ConstitutionVersion {
  sha: string;
  shortSha: string;
  date: string;
  relativeDate: string;
  subject: string;
  author: string;
}

export default function ConstitutionTab({ text, projectName }: { text: string; projectName?: string }) {
  const [draft, setDraft] = useState(text);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');

  // Version history state
  const [versions, setVersions] = useState<ConstitutionVersion[]>([]);
  const [selectedSha, setSelectedSha] = useState<string | null>(null); // null = current/live
  const [versionContent, setVersionContent] = useState('');
  const [loadingVersion, setLoadingVersion] = useState(false);
  const [versionsLoaded, setVersionsLoaded] = useState(false);

  useEffect(() => { setDraft(text); }, [text]);

  // Fetch version history on mount
  useEffect(() => {
    if (versionsLoaded) return;
    (async () => {
      try {
        const res = await fetch(`/api/constitution-versions?name=${encodeURIComponent(projectName ?? '')}`);
        const data = await res.json() as { versions: ConstitutionVersion[] };
        setVersions(data.versions ?? []);
      } catch { /* ignore */ }
      setVersionsLoaded(true);
    })();
  }, [projectName, versionsLoaded]);

  // Fetch content when a historical version is selected
  useEffect(() => {
    if (!selectedSha) { setVersionContent(''); return; }
    let cancelled = false;
    setLoadingVersion(true);
    (async () => {
      try {
        const res = await fetch(`/api/constitution-version?name=${encodeURIComponent(projectName ?? '')}&sha=${encodeURIComponent(selectedSha)}`);
        const data = await res.json() as { content: string };
        if (!cancelled) setVersionContent(data.content ?? '');
      } catch { /* ignore */ }
      if (!cancelled) setLoadingVersion(false);
    })();
    return () => { cancelled = true; };
  }, [selectedSha, projectName]);

  if (!text && draft === '' && versions.length === 0) {
    return (
      <div className="p-6 text-slate-500">
        No constitution found. Set <code className="bg-slate-100 px-1 rounded">SPIRAL_SPECKIT_CONSTITUTION</code> in your config,
        or create <code className="bg-slate-100 px-1 rounded">.specify/memory/constitution.md</code> in your project root.
      </div>
    );
  }

  const isViewingHistory = selectedSha !== null;
  const displayText = isViewingHistory ? versionContent : draft;
  const lineCount = displayText.split('\n').length;
  const isTooLong = !isViewingHistory && lineCount > 150;
  const isDirty = draft !== text;

  async function handleSave() {
    setSaving(true);
    setError('');
    try {
      const res = await fetch('/api/save-constitution', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: draft, name: projectName }),
      });
      const data = await res.json() as { ok?: boolean; error?: string };
      if (!data.ok) throw new Error(data.error ?? 'Save failed');
      setSaved(true);
      setVersionsLoaded(false); // refresh version list after save
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  function handleRestore() {
    if (!versionContent) return;
    setDraft(versionContent);
    setSelectedSha(null);
  }

  return (
    <div className="flex h-full">
      {/* Left sidebar — version history */}
      <div className="w-56 shrink-0 border-r border-slate-200 bg-slate-50 flex flex-col">
        <div className="px-3 py-2.5 border-b border-slate-200 bg-white">
          <span className="text-xs font-semibold text-slate-600 uppercase tracking-wide">Versions</span>
          <span className="ml-1.5 text-[10px] text-slate-400">{versions.length}</span>
        </div>
        <div className="flex-1 overflow-y-auto">
          {/* Current / live entry */}
          <button
            onClick={() => setSelectedSha(null)}
            className={`w-full text-left px-3 py-2 border-b border-slate-100 transition-colors ${
              !isViewingHistory
                ? 'bg-blue-50 border-l-2 border-l-blue-500'
                : 'hover:bg-slate-100 border-l-2 border-l-transparent'
            }`}
          >
            <div className="flex items-center gap-1.5">
              <span className={`w-2 h-2 rounded-full ${isDirty ? 'bg-amber-400' : 'bg-green-400'}`} />
              <span className="text-xs font-semibold text-slate-800">Current</span>
            </div>
            <div className="text-[10px] text-slate-400 mt-0.5">{isDirty ? 'unsaved changes' : 'live version'}</div>
          </button>

          {/* Historical versions */}
          {versions.map(v => (
            <button
              key={v.sha}
              onClick={() => setSelectedSha(v.sha)}
              className={`w-full text-left px-3 py-2 border-b border-slate-100 transition-colors ${
                selectedSha === v.sha
                  ? 'bg-blue-50 border-l-2 border-l-blue-500'
                  : 'hover:bg-slate-100 border-l-2 border-l-transparent'
              }`}
            >
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] font-mono text-slate-500">{v.shortSha}</span>
                <span className="text-[10px] text-slate-400">{v.relativeDate}</span>
              </div>
              <div className="text-[11px] text-slate-700 mt-0.5 line-clamp-2 leading-tight">{v.subject}</div>
            </button>
          ))}

          {versions.length === 0 && versionsLoaded && (
            <div className="px-3 py-4 text-[11px] text-slate-400 text-center">No git history found</div>
          )}
        </div>
      </div>

      {/* Right content area — editor or read-only viewer */}
      <div className="flex-1 flex flex-col overflow-hidden p-6 gap-3">
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-500 font-mono">{lineCount} lines</span>
          {isViewingHistory && (
            <span className="flex items-center gap-1 text-xs font-medium text-blue-700 bg-blue-50 border border-blue-200 rounded px-2 py-0.5">
              Viewing {versions.find(v => v.sha === selectedSha)?.shortSha} — {versions.find(v => v.sha === selectedSha)?.relativeDate}
            </span>
          )}
          {isTooLong && (
            <span className="flex items-center gap-1 text-xs font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-0.5">
              Constitution is long ({lineCount} lines). Consider trimming — LLMs may not reliably follow rules past ~150 lines.
            </span>
          )}
          <div className="ml-auto flex items-center gap-2">
            {error && <span className="text-xs text-red-600">{error}</span>}
            {saved && <span className="text-xs text-green-600 font-medium">Saved</span>}
            {isViewingHistory ? (
              <button
                onClick={handleRestore}
                disabled={loadingVersion || !versionContent}
                className="px-3 py-1 text-xs font-medium rounded transition-colors bg-amber-500 hover:bg-amber-600 text-white disabled:opacity-50"
              >
                Restore this version
              </button>
            ) : (
              <button
                onClick={handleSave}
                disabled={saving || !isDirty}
                className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
                  isDirty
                    ? 'bg-blue-600 hover:bg-blue-700 text-white'
                    : 'bg-slate-100 text-slate-400 cursor-not-allowed'
                }`}
              >
                {saving ? 'Saving...' : 'Save'}
              </button>
            )}
          </div>
        </div>
        {loadingVersion ? (
          <div className="flex-1 flex items-center justify-center text-sm text-slate-400">Loading version...</div>
        ) : (
          <textarea
            value={displayText}
            onChange={isViewingHistory ? undefined : (e => setDraft(e.target.value))}
            readOnly={isViewingHistory}
            className={`flex-1 w-full rounded-xl border p-5 text-xs font-mono leading-relaxed resize-none focus:outline-none focus:ring-2 ${
              isViewingHistory
                ? 'border-slate-200 bg-slate-50 text-slate-600 focus:ring-slate-300 cursor-default'
                : 'border-slate-200 bg-white text-slate-700 focus:ring-blue-300'
            }`}
            spellCheck={false}
            style={{ minHeight: '400px' }}
          />
        )}
      </div>
    </div>
  );
}
