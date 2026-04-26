import { useState } from 'react';
import { useTestResults } from '../hooks/useTestResults';
import TestDetailModal from '../components/TestDetailModal';
import type { TestSummary } from '../hooks/useTestResults';

export default function TestsTab() {
  const { data: testResults, loading, error } = useTestResults();
  const [selectedStory, setSelectedStory] = useState<TestSummary | null>(null);

  if (loading) {
    return (
      <div className="p-6 text-sm text-slate-500">
        Loading test results…
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 text-sm text-red-500">
        Error loading test results: {error}
      </div>
    );
  }

  if (testResults.length === 0) {
    return (
      <div className="p-6 text-center text-slate-500">
        <div className="text-3xl mb-2">📊</div>
        <div className="text-sm font-medium">No test results yet</div>
        <div className="text-xs mt-1 text-slate-400">
          Run SPIRAL to generate test verification events
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex-1 overflow-auto">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 bg-slate-100 border-b border-slate-300">
            <tr>
              <th className="px-4 py-2 text-left font-semibold text-slate-700 border-r border-slate-300">
                Story ID
              </th>
              <th className="px-4 py-2 text-left font-semibold text-slate-700 border-r border-slate-300">
                Test Status
              </th>
              <th className="px-4 py-2 text-center font-semibold text-slate-700 border-r border-slate-300">
                Test Count
              </th>
              <th className="px-4 py-2 text-center font-semibold text-slate-700 border-r border-slate-300">
                File-Touch OK
              </th>
              <th className="px-4 py-2 text-center font-semibold text-slate-700">
                Coverage %
              </th>
            </tr>
          </thead>
          <tbody>
            {testResults.map((story) => (
              <tr
                key={story.story_id}
                onClick={() => setSelectedStory(story)}
                className="border-b border-slate-200 hover:bg-blue-50 cursor-pointer transition-colors"
              >
                <td className="px-4 py-3 font-mono text-slate-700 border-r border-slate-200">
                  {story.story_id}
                </td>
                <td className="px-4 py-3 text-slate-600 border-r border-slate-200">
                  {story.test_status || '—'}
                </td>
                <td className="px-4 py-3 text-center text-slate-600 border-r border-slate-200">
                  {story.test_count}
                </td>
                <td className="px-4 py-3 text-center border-r border-slate-200">
                  <span
                    className={`inline-flex items-center justify-center w-6 h-6 rounded ${
                      story.file_touch_ok
                        ? 'bg-emerald-100 text-emerald-700'
                        : 'bg-red-100 text-red-700'
                    }`}
                  >
                    {story.file_touch_ok ? '✓' : '✗'}
                  </span>
                </td>
                <td className="px-4 py-3 text-center">
                  <div className="inline-block px-2 py-1 rounded bg-slate-100 text-slate-700 font-medium">
                    {story.coverage_pct}%
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <TestDetailModal
        story={selectedStory}
        onClose={() => setSelectedStory(null)}
      />
    </div>
  );
}
