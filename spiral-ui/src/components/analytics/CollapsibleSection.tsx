import { useState, type ReactNode } from 'react';

interface Props {
  title: string;
  badge?: string | number;
  badgeColor?: string;
  defaultOpen?: boolean;
  children: ReactNode;
}

export default function CollapsibleSection({ title, badge, badgeColor = 'bg-slate-100 text-slate-500', defaultOpen = false, children }: Props) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="border border-slate-200 rounded-lg overflow-hidden">
      <button
        className="w-full flex items-center justify-between px-3 py-1.5 bg-slate-50 hover:bg-slate-100 text-left transition-colors"
        onClick={() => setOpen(o => !o)}
      >
        <div className="flex items-center gap-2">
          <span className="text-slate-400 text-[10px] w-3 shrink-0">{open ? '\u25BE' : '\u25B8'}</span>
          <span className="text-xs font-medium text-slate-500 uppercase tracking-wide">{title}</span>
        </div>
        {badge != null && (
          <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${badgeColor}`}>
            {badge}
          </span>
        )}
      </button>
      {open && <div className="border-t border-slate-200 p-3">{children}</div>}
    </div>
  );
}
