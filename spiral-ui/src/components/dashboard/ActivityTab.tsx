import { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import type { ActiveStoryInfo } from './types';
import ActiveStoryBanner from './ActiveStoryBanner';

/** Convert ISO/UTC timestamps in a log line to Malaysia time (MYT, UTC+8). */
function toMYT(line: string): string {
  // Match ISO timestamps: 2026-03-16T10:30:45Z or 2026-03-16T10:30:45.123Z or +00:00
  return line.replace(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})/g, (match) => {
    try {
      return new Date(match).toLocaleString('en-MY', { timeZone: 'Asia/Kuala_Lumpur', hour12: false, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch { return match; }
  });
}

/** Strip ANSI escape sequences from a string. */

export default function ActivityTab({ log, activeStory }: { log: string; activeStory: ActiveStoryInfo | null }) {
  const [maximized, setMaximized] = useState(false);
  const [copied, setCopied] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!maximized) return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setMaximized(false); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [maximized]);

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [log, autoScroll, maximized]);

  if (!log) {
    return <div className="p-6 text-slate-500">No activity log yet. Start SPIRAL to see live output here.</div>;
  }

  const lines = log.split('\n').filter(Boolean);
  const processed = lines.map(toMYT).join('\n');
  const now = new Date().toLocaleString('en-MY', { timeZone: 'Asia/Kuala_Lumpur', hour12: false });

  const handleCopy = () => {
    void navigator.clipboard.writeText(processed);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    if (!atBottom) setAutoScroll(false);
  };

  const toolbar = (
    <div className="flex items-center justify-between px-3 py-1.5 bg-slate-900 border-b border-slate-800">
      <span className="text-[10px] text-slate-500 font-mono">
        {lines.length} lines · elapsed→MYT
        {maximized && <span className="ml-2 text-blue-400">Activity Log</span>}
      </span>
      <div className="flex items-center gap-1">
        <button
          onClick={() => { setAutoScroll(true); if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight; }}
          title="Scroll to bottom"
          className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono transition-all ${
            autoScroll ? 'bg-emerald-700 text-white' : 'bg-slate-700 hover:bg-slate-600 text-slate-300'
          }`}
        >
          ↓ Bottom
        </button>
        <button
          onClick={() => setMaximized(prev => !prev)}
          title={maximized ? 'Restore (Esc)' : 'Maximize to fullscreen'}
          className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono transition-all ${
            maximized ? 'bg-blue-600 text-white' : 'bg-slate-700 hover:bg-slate-600 text-slate-300'
          }`}
        >
          {maximized ? '⊡ Restore' : '⊞ Max'}
        </button>
        <button
          onClick={handleCopy}
          title="Copy log to clipboard"
          className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono transition-all ${
            copied ? 'bg-emerald-600 text-white' : 'bg-slate-700 hover:bg-slate-600 text-slate-300'
          }`}
        >
          {copied ? '✓ Copied' : '⎘ Copy'}
        </button>
      </div>
    </div>
  );

  const logBody = (
    <div
      ref={scrollRef}
      onScroll={handleScroll}
      className={`overflow-auto ${maximized ? 'flex-1' : 'max-h-[600px]'}`}
    >
      <pre className="p-4 text-[11px] text-slate-300 font-mono leading-relaxed whitespace-pre-wrap">
        {processed}
      </pre>
    </div>
  );

  const inner = (
    <div className={`rounded-xl bg-slate-950 overflow-hidden ${maximized ? 'flex flex-col h-full' : ''}`}>
      {toolbar}
      {logBody}
    </div>
  );

  return (
    <div className="p-6 space-y-3">
      <ActiveStoryBanner activeStory={activeStory} />
      <div className="flex items-center justify-between">
        <div className="text-[10px] text-slate-400">Timestamps shown in Malaysia Time (MYT, UTC+8)</div>
        <div className="text-[10px] text-slate-400">Now: {now}</div>
      </div>
      {maximized
        ? createPortal(
            <div className="fixed inset-0 z-[9999] bg-slate-950 flex flex-col p-4">
              <ActiveStoryBanner activeStory={activeStory} className="mb-2" />
              <div className="flex-1 flex flex-col min-h-0 rounded-xl overflow-hidden">
                {toolbar}
                {logBody}
              </div>
            </div>,
            document.body
          )
        : inner
      }
    </div>
  );
}
