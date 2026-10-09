import React from 'react';

export type StatusType = 'healthy' | 'warning' | 'critical' | 'neutral' | 'info';

interface StatusIndicatorProps {
  status: StatusType;
  label: string;
  size?: 'sm' | 'md';
  className?: string;
}

export const StatusIndicator: React.FC<StatusIndicatorProps> = ({
  status,
  label,
  className = '',
}) => {
  const dotColor = {
    healthy: 'bg-emerald-500',
    warning: 'bg-amber-500',
    critical: 'bg-rose-500',
    neutral: 'bg-slate-400',
    info: 'bg-blue-500',
  }[status];

  const textColor = {
    healthy: 'text-emerald-700',
    warning: 'text-amber-800',
    critical: 'text-rose-700',
    neutral: 'text-slate-600',
    info: 'text-blue-700',
  }[status];

  const bgBorder = {
    healthy: 'bg-emerald-50/70 border-emerald-200/80',
    warning: 'bg-amber-50/70 border-amber-200/80',
    critical: 'bg-rose-50/70 border-rose-200/80',
    neutral: 'bg-slate-100/70 border-slate-200/80',
    info: 'bg-blue-50/70 border-blue-200/80',
  }[status];

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded border text-xs font-medium tracking-tight ${bgBorder} ${textColor} ${className}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dotColor}`} />
      <span>{label}</span>
    </span>
  );
};

export const MetadataText: React.FC<{ items: React.ReactNode[]; className?: string }> = ({
  items,
  className = 'text-xs text-slate-500',
}) => {
  return (
    <div className={`flex items-center flex-wrap gap-x-2 gap-y-1 ${className}`}>
      {items.map((item, idx) => (
        <React.Fragment key={idx}>
          {idx > 0 && <span className="text-slate-300 select-none">·</span>}
          <span>{item}</span>
        </React.Fragment>
      ))}
    </div>
  );
};
