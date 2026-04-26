import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import type { TestSummary } from '../hooks/useTestResults';

interface TestDetailModalProps {
  story: TestSummary | null;
  onClose: () => void;
}

export default function TestDetailModal({ story, onClose }: TestDetailModalProps) {
  if (!story) return null;

  const handleBackgroundClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  const handleEscKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      onClose();
    }
  };

  useEffect(() => {
    window.addEventListener('keydown', handleEscKey);
    return () => window.removeEventListener('keydown', handleEscKey);
  }, []);

  const content = (
    <div
      className="fixed inset-0 z-[1000] bg-black/50 flex items-center justify-center p-4"
      onClick={handleBackgroundClick}
    >
      <div className="bg-white rounded-lg shadow-lg max-w-2xl w-full max-h-[80vh] overflow-auto">
        <div className="sticky top-0 bg-white border-b border-slate-200 px-6 py-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900">{story.story_id}</h2>
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-slate-700 transition-colors text-xl"
            title="Close (Esc)"
          >
            ✕
          </button>
        </div>
        <div className="p-6 space-y-6">
          <div>
            <h3 className="text-sm font-semibold text-slate-700 mb-2">Test Status</h3>
            <p className="text-slate-600">{story.test_status || 'N/A'}</p>
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <h3 className="text-sm font-semibold text-slate-700 mb-2">Test Count</h3>
              <p className="text-2xl font-bold text-slate-900">{story.test_count}</p>
            </div>
            <div>
              <h3 className="text-sm font-semibold text-slate-700 mb-2">File-Touch OK</h3>
              <p
                className={`text-2xl font-bold ${
                  story.file_touch_ok ? 'text-emerald-600' : 'text-red-600'
                }`}
              >
                {story.file_touch_ok ? '✓' : '✗'}
              </p>
            </div>
            <div>
              <h3 className="text-sm font-semibold text-slate-700 mb-2">Coverage</h3>
              <p className="text-2xl font-bold text-slate-900">{story.coverage_pct}%</p>
            </div>
          </div>
          <div>
            <h3 className="text-sm font-semibold text-slate-700 mb-2">Raw Data</h3>
            <pre className="bg-slate-100 p-3 rounded text-xs overflow-auto max-h-[300px]">
              {JSON.stringify(story, null, 2)}
            </pre>
          </div>
        </div>
      </div>
    </div>
  );

  return createPortal(content, document.body);
}
