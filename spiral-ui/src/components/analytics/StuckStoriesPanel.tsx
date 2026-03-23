import { useState, useEffect } from 'react';

// ── Types ──────────────────────────────────────────────────────────────────────

interface StuckStory {
  story_id: string;
  attempt_count: number;
  last_model_tried: string;
  escalation_chain: string;
  original_token_count: number;
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function suggestDecomposition(story: StuckStory): string {
  const hints: string[] = [];

  if (story.attempt_count >= 5) {
    hints.push(`Story exhausted ${story.attempt_count} attempts — split into 3–4 atomic sub-stories.`);
  } else {
    hints.push(`Split into 2–3 atomic sub-stories (one per acceptance criterion).`);
  }

  if (story.escalation_chain.includes('opus')) {
    hints.push(`Model escalated to opus — scope is too broad for a single story.`);
  }

  if (story.original_token_count > 50_000) {
    hints.push(`High token usage (${(story.original_token_count / 1000).toFixed(0)}K) — separate API, UI, and tests into distinct stories.`);
  } else if (story.original_token_count > 20_000) {
    hints.push(`Moderate token usage (${(story.original_token_count / 1000).toFixed(0)}K) — consider splitting implementation from tests.`);
  }

  hints.push(`Each sub-story should touch ≤ 3 files and have a single clear acceptance criterion.`);

  return hints.join(' ');
}

const MODEL_BADGE: Record<string, string> = {
  haiku: 'bg-sky-100 text-sky-700',
  sonnet: 'bg-violet-100 text-violet-700',
  opus: 'bg-rose-100 text-rose-700',
};

function ModelBadge({ model }: { model: string }) {
  const cls = MODEL_BADGE[model.toLowerCase()] ?? 'bg-slate-100 text-slate-600';
  return <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${cls}`}>{model}</span>;
}

// ── Component ──────────────────────────────────────────────────────────────────

export default function StuckStoriesPanel() {
  const [stories, setStories] = useState<StuckStory[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedHint, setExpandedHint] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/dashboard/stuck-stories')
      .then(r => r.ok ? r.json() as Promise<StuckStory[]> : Promise.resolve([]))
      .then(data => { setStories(data); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-xs text-slate-400 py-2">Loading stuck stories...</div>;
  if (stories.length === 0) return null;

  return (
    <div className="rounded-lg border border-orange-200 bg-orange-50 overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-orange-200 bg-orange-100">
        <span className="text-[11px] font-semibold text-orange-800 uppercase tracking-wide">
          Stuck Stories
        </span>
        <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-orange-200 text-orange-700 font-medium">
          {stories.length}
        </span>
        <span className="text-[10px] text-orange-600 ml-auto">3+ retry attempts</span>
      </div>

      <table className="w-full text-[11px]">
        <thead className="bg-orange-50 text-orange-700 border-b border-orange-200">
          <tr>
            <th className="text-left px-2 py-1.5">Story</th>
            <th className="text-center px-2 py-1.5">Attempts</th>
            <th className="text-left px-2 py-1.5">Escalation</th>
            <th className="text-right px-2 py-1.5">Tokens</th>
            <th className="px-2 py-1.5" />
          </tr>
        </thead>
        <tbody className="divide-y divide-orange-100">
          {stories.map(s => (
            <>
              <tr key={s.story_id} className="hover:bg-orange-50/70">
                <td className="px-2 py-1.5 font-mono text-slate-700 font-medium">{s.story_id}</td>
                <td className="px-2 py-1.5 text-center">
                  <span className={`font-bold ${s.attempt_count >= 5 ? 'text-red-600' : 'text-orange-600'}`}>
                    {s.attempt_count}
                  </span>
                </td>
                <td className="px-2 py-1.5">
                  <div className="flex items-center gap-1 flex-wrap">
                    {s.escalation_chain.split('→').map((m, i) => (
                      <span key={i} className="flex items-center gap-0.5">
                        {i > 0 && <span className="text-orange-300">→</span>}
                        <ModelBadge model={m} />
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-2 py-1.5 text-right text-slate-500">
                  {s.original_token_count > 0
                    ? `${(s.original_token_count / 1000).toFixed(0)}K`
                    : '—'}
                </td>
                <td className="px-2 py-1.5 text-right">
                  <button
                    onClick={() => setExpandedHint(expandedHint === s.story_id ? null : s.story_id)}
                    className="text-[10px] px-2 py-0.5 rounded border border-orange-300 text-orange-700 hover:bg-orange-200 transition-colors"
                  >
                    {expandedHint === s.story_id ? 'Hide' : 'Suggest Decomposition'}
                  </button>
                </td>
              </tr>
              {expandedHint === s.story_id && (
                <tr key={`${s.story_id}-hint`}>
                  <td colSpan={5} className="px-3 py-2 bg-amber-50 border-t border-amber-200">
                    <div className="text-[11px] text-amber-800">
                      <span className="font-semibold">Decomposition hint: </span>
                      {suggestDecomposition(s)}
                    </div>
                  </td>
                </tr>
              )}
            </>
          ))}
        </tbody>
      </table>
    </div>
  );
}
