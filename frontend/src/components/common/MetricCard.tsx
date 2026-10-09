import React from 'react';

interface MetricCardProps {
  label: string;
  value: string | number;
  unit?: string;
  subtext?: string;
  delta?: {
    value: string;
    isPositive?: boolean;
    isNeutral?: boolean;
  };
  icon?: React.ReactNode;
  badge?: React.ReactNode;
  className?: string;
  onClick?: () => void;
}

export const MetricCard: React.FC<MetricCardProps> = ({
  label,
  value,
  unit,
  subtext,
  delta,
  icon,
  badge,
  className = '',
  onClick,
}) => {
  return (
    <div
      onClick={onClick}
      className={`bg-white border border-slate-200/90 rounded-lg p-3.5 shadow-2xs flex flex-col justify-between ${
        onClick ? 'cursor-pointer hover:border-slate-300 transition-all' : ''
      } ${className}`}
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <span className="text-xs font-medium text-slate-500 uppercase tracking-wider">
          {label}
        </span>
        <div className="flex items-center gap-1.5 shrink-0">
          {badge}
          {icon && <div className="text-slate-400">{icon}</div>}
        </div>
      </div>

      <div className="flex items-baseline gap-2">
        <div className="text-2xl font-bold tracking-tight text-slate-900 font-sans tabular-nums">
          {value}
          {unit && <span className="text-sm font-normal text-slate-500 ml-1">{unit}</span>}
        </div>

        {delta && (
          <span
            className={`text-xs font-mono font-medium ${
              delta.isNeutral
                ? 'text-slate-500'
                : delta.isPositive
                ? 'text-emerald-700'
                : 'text-amber-700'
            }`}
          >
            {delta.value}
          </span>
        )}
      </div>

      {subtext && <p className="text-xs text-slate-500 mt-1 truncate">{subtext}</p>}
    </div>
  );
};
