import { useState, useEffect, useRef } from 'react';

// ── Tests tab ────────────────────────────────────────────────────────────────

interface TestItem { id: string; cls: string; name: string; }
interface TestFileEntry { name: string; path: string; tests: TestItem[]; }

export default function TestsTab({ projectName }: { projectName: string }) {
  const [files, setFiles] = useState<TestFileEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [running, setRunning] = useState(false);
  const [output, setOutput] = useState<string | null>(null);
  const [summary, setSummary] = useState<{ passed: number; failed: number; errors: number; total: number } | null>(null);
  const [lastResults, setLastResults] = useState<Record<string, 'passed' | 'failed' | 'error'>>({});
  const outputRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    fetch(`/api/tests?name=${encodeURIComponent(projectName)}`)
      .then(r => r.json() as Promise<{ files: TestFileEntry[]; total: number; error?: string }>)
      .then(d => {
        if (d.error) setFetchError(d.error);
        else setFiles(d.files ?? []);
        setLoading(false);
      })
      .catch(e => { setFetchError(String(e)); setLoading(false); });
  }, [projectName]);

  useEffect(() => {
    if (outputRef.current) outputRef.current.scrollTop = outputRef.current.scrollHeight;
  }, [output]);

  const totalTests = files.reduce((s, f) => s + f.tests.length, 0);

  const filteredFiles = filter.trim()
    ? files
        .map(f => ({ ...f, tests: f.tests.filter(t => t.id.toLowerCase().includes(filter.toLowerCase()) || t.name.toLowerCase().includes(filter.toLowerCase())) }))
        .filter(f => f.tests.length > 0)
    : files;

  const allFilteredIds = filteredFiles.flatMap(f => f.tests.map(t => t.id));

  const toggleTest = (id: string) => {
    setSelected(prev => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  };
  const toggleFile = (file: TestFileEntry) => {
    const ids = file.tests.map(t => t.id);
    const allSel = ids.every(id => selected.has(id));
    setSelected(prev => { const n = new Set(prev); if (allSel) ids.forEach(id => n.delete(id)); else ids.forEach(id => n.add(id)); return n; });
  };
  const toggleExpanded = (p: string) => {
    setExpanded(prev => { const n = new Set(prev); if (n.has(p)) n.delete(p); else n.add(p); return n; });
  };

  const runTests = async () => {
    setRunning(true);
    setOutput(null);
    setSummary(null);
    try {
      const testIds = selected.size > 0 ? Array.from(selected) : [];
      const res = await fetch('/api/run-tests', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: projectName, testIds }),
      });
      type RunResult = { output: string; passed: number; failed: number; errors: number; total: number; testResults: Record<string, string>; error?: string };
      const data = await res.json() as RunResult;
      if (data.error) {
        setOutput(`Error: ${data.error}`);
      } else {
        setOutput(data.output ?? '');
        setSummary({ passed: data.passed ?? 0, failed: data.failed ?? 0, errors: data.errors ?? 0, total: data.total ?? 0 });
        setLastResults((data.testResults ?? {}) as Record<string, 'passed' | 'failed' | 'error'>);
      }
    } catch (e) {
      setOutput(`Request error: ${String(e)}`);
    } finally {
      setRunning(false);
    }
  };

  if (loading) return <div className="p-6 text-sm text-slate-500">Loading tests…</div>;
  if (fetchError) return <div className="p-6 text-sm text-red-500">Error loading tests: {fetchError}</div>;

  const selCount = selected.size;

  return (
    <div className="h-full flex flex-col">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-slate-200 bg-white flex-shrink-0 flex-wrap">
        <span className="text-xs text-slate-500 font-medium whitespace-nowrap">{totalTests} tests</span>
        <input
          type="text"
          placeholder="Filter tests…"
          value={filter}
          onChange={e => setFilter(e.target.value)}
          className="w-52 border border-slate-300 rounded px-2 py-1 text-xs focus:outline-none focus:border-blue-400"
        />
        <button
          onClick={() => setSelected(new Set(allFilteredIds))}
          className="text-xs px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-600 transition-colors whitespace-nowrap"
        >Select All</button>
        <button
          onClick={() => setSelected(new Set())}
          className="text-xs px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-600 transition-colors"
        >Clear</button>
        <button
          onClick={runTests}
          disabled={running}
          className={`text-xs px-3 py-1 rounded font-semibold transition-colors whitespace-nowrap ${
            running ? 'bg-slate-200 text-slate-400 cursor-not-allowed' : 'bg-blue-600 hover:bg-blue-700 text-white shadow-sm'
          }`}
        >
          {running ? '⏳ Running…' : selCount > 0 ? `▶ Run Selected (${selCount})` : '▶ Run All'}
        </button>
        {summary && (
          <div className="flex items-center gap-2 text-xs">
            {summary.passed > 0 && <span className="text-emerald-600 font-semibold">✓ {summary.passed} passed</span>}
            {summary.failed > 0 && <span className="text-red-600 font-semibold">✗ {summary.failed} failed</span>}
            {summary.errors > 0 && <span className="text-orange-500 font-semibold">! {summary.errors} error</span>}
            <span className="text-slate-400">({summary.total} total)</span>
          </div>
        )}
      </div>

      {/* Split pane */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left: test tree */}
        <div className="w-80 flex-shrink-0 border-r border-slate-200 overflow-y-auto bg-white">
          {filteredFiles.length === 0 && (
            <div className="p-4 text-xs text-slate-400 text-center">No tests match filter</div>
          )}
          {filteredFiles.map(file => {
            const isOpen = expanded.has(file.path);
            const fileSel = file.tests.filter(t => selected.has(t.id)).length;
            const allSel = fileSel === file.tests.length && file.tests.length > 0;
            const partSel = fileSel > 0 && !allSel;
            return (
              <div key={file.path} className="border-b border-slate-100">
                <div
                  className="flex items-center gap-1.5 px-2 py-1.5 hover:bg-slate-50 cursor-pointer select-none"
                  onClick={() => toggleExpanded(file.path)}
                >
                  <input
                    type="checkbox"
                    checked={allSel}
                    ref={el => { if (el) el.indeterminate = partSel; }}
                    onChange={() => toggleFile(file)}
                    onClick={e => e.stopPropagation()}
                    className="w-3 h-3 accent-blue-600 flex-shrink-0"
                  />
                  <span className="text-[10px] text-slate-400 w-3 flex-shrink-0">{isOpen ? '▾' : '▸'}</span>
                  <span className="text-[11px] font-mono font-semibold text-slate-700 truncate flex-1">{file.name}</span>
                  <span className="text-[10px] text-slate-400 flex-shrink-0">{fileSel}/{file.tests.length}</span>
                </div>
                {isOpen && file.tests.map(test => {
                  const result = lastResults[test.id];
                  return (
                    <div
                      key={test.id}
                      className={`flex items-center gap-1.5 pl-7 pr-2 py-0.5 hover:bg-slate-50 cursor-pointer ${selected.has(test.id) ? 'bg-blue-50' : ''}`}
                      onClick={() => toggleTest(test.id)}
                    >
                      <input
                        type="checkbox"
                        checked={selected.has(test.id)}
                        onChange={() => toggleTest(test.id)}
                        onClick={e => e.stopPropagation()}
                        className="w-3 h-3 accent-blue-600 flex-shrink-0"
                      />
                      <span className="w-3 flex-shrink-0 text-[10px] leading-none">
                        {result === 'passed' && <span className="text-emerald-500">✓</span>}
                        {result === 'failed' && <span className="text-red-500">✗</span>}
                        {result === 'error'  && <span className="text-orange-500">!</span>}
                      </span>
                      <span className="text-[11px] font-mono text-slate-600 truncate">{test.name}</span>
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>

        {/* Right: output console */}
        <div className="flex-1 bg-slate-950 overflow-hidden flex flex-col">
          {output === null && !running ? (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center text-slate-500">
                <div className="text-4xl mb-3">🧪</div>
                <div className="text-sm font-medium">No results yet</div>
                <div className="text-xs mt-1 text-slate-600">Select tests and click Run, or click ▶ Run All</div>
              </div>
            </div>
          ) : running ? (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center text-slate-400">
                <div className="text-3xl mb-3">⏳</div>
                <div className="text-sm">Running tests…</div>
                <div className="text-xs mt-1 text-slate-600">This may take a while for large suites</div>
              </div>
            </div>
          ) : (
            <pre
              ref={outputRef}
              className="flex-1 overflow-y-auto p-4 text-[11px] font-mono leading-relaxed text-slate-200 whitespace-pre-wrap break-all"
            >
              {output}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}
