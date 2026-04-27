import { useState } from 'react';

interface Story {
  id: string;
  title: string;
  description?: string;
  status: 'passed' | 'failed' | 'pending';
  duration?: number;
  model?: string;
  source?: string;
}

interface ActivityLogTableProps {
  stories: Story[];
}

const statusColors: Record<string, string> = {
  passed: 'bg-emerald-100 text-emerald-700',
  failed: 'bg-red-100 text-red-700',
  pending: 'bg-amber-100 text-amber-700',
};

export function StoryDetailModal({ story, onClose }: { story: Story | null; onClose: () => void }) {
  if (!story) return null;

  return (
    <div
      data-testid="story-detail-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg shadow-lg p-6 max-w-md w-full mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-xl font-semibold mb-4 text-slate-800" data-testid="modal-title">
          {story.title}
        </h2>
        <p className="text-sm text-slate-600 mb-4" data-testid="modal-description">
          {story.description || 'No description available'}
        </p>
        <div className="grid grid-cols-2 gap-4 mb-4">
          <div>
            <span className="text-xs font-semibold text-slate-500">ID</span>
            <p className="text-sm text-slate-700">{story.id}</p>
          </div>
          <div>
            <span className="text-xs font-semibold text-slate-500">Status</span>
            <p className={`text-sm px-2 py-1 rounded-full inline-block ${statusColors[story.status]}`}>
              {story.status}
            </p>
          </div>
        </div>
        {story.model && (
          <div className="mb-4">
            <span className="text-xs font-semibold text-slate-500">Model</span>
            <p className="text-sm text-slate-700">{story.model}</p>
          </div>
        )}
        <button
          onClick={onClose}
          className="w-full bg-blue-600 text-white py-2 rounded-lg hover:bg-blue-700 transition-colors"
        >
          Close
        </button>
      </div>
    </div>
  );
}

export default function ActivityLogTable({ stories }: ActivityLogTableProps) {
  const [activeFilter, setActiveFilter] = useState<string | null>(null);
  const [selectedStory, setSelectedStory] = useState<Story | null>(null);

  const filteredStories = activeFilter
    ? stories.filter((s) => s.status === activeFilter)
    : stories;

  const formatDuration = (seconds?: number): string => {
    if (!seconds) return '—';
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}m ${secs}s`;
  };

  const toggleFilter = (status: string) => {
    setActiveFilter(activeFilter === status ? null : status);
  };

  const uniqueStatuses = Array.from(new Set(stories.map((s) => s.status)));

  return (
    <div className="p-6 space-y-4">
      {/* Status filter badges */}
      <div className="flex gap-2 flex-wrap">
        {uniqueStatuses.map((status) => (
          <button
            key={status}
            onClick={() => toggleFilter(status)}
            data-testid={`status-badge-${status}`}
            className={`px-3 py-1.5 rounded-full text-sm font-medium transition-all ${
              activeFilter === status
                ? `${statusColors[status]} ring-2 ring-offset-2 ring-${status === 'passed' ? 'emerald' : status === 'failed' ? 'red' : 'amber'}-600`
                : statusColors[status]
            }`}
          >
            {status}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-b border-slate-200">
              <th className="px-4 py-2 text-left text-xs font-semibold text-slate-700">ID</th>
              <th className="px-4 py-2 text-left text-xs font-semibold text-slate-700">Status</th>
              <th className="px-4 py-2 text-left text-xs font-semibold text-slate-700">Duration</th>
              <th className="px-4 py-2 text-left text-xs font-semibold text-slate-700">Model</th>
              <th className="px-4 py-2 text-left text-xs font-semibold text-slate-700">Source</th>
            </tr>
          </thead>
          <tbody>
            {filteredStories.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-3 text-center text-sm text-slate-500">
                  No stories found
                </td>
              </tr>
            ) : (
              filteredStories.map((story) => (
                <tr
                  key={story.id}
                  onClick={() => setSelectedStory(story)}
                  data-testid={`story-row-${story.id}`}
                  className="border-b border-slate-100 hover:bg-slate-50 cursor-pointer transition-colors"
                >
                  <td className="px-4 py-3 text-sm text-slate-700">{story.id}</td>
                  <td className="px-4 py-3 text-sm">
                    <span
                      className={`px-2 py-1 rounded-full text-xs font-medium ${statusColors[story.status]}`}
                    >
                      {story.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-600">{formatDuration(story.duration)}</td>
                  <td className="px-4 py-3 text-sm text-slate-600">{story.model || '—'}</td>
                  <td className="px-4 py-3 text-sm text-slate-600">{story.source || '—'}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Modal */}
      <StoryDetailModal story={selectedStory} onClose={() => setSelectedStory(null)} />
    </div>
  );
}
