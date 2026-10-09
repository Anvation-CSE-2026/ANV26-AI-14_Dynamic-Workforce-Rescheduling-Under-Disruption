import React from 'react';

export interface TabItem<T = string> {
  id: T;
  label: string;
  badge?: number | string;
  icon?: React.ReactNode;
}

interface TabsProps<T = string> {
  items: TabItem<T>[];
  activeId: T;
  onChange: (id: T) => void;
  variant?: 'segmented' | 'underline';
  className?: string;
}

export function Tabs<T extends string = string>({
  items,
  activeId,
  onChange,
  variant = 'segmented',
  className = '',
}: TabsProps<T>) {
  if (variant === 'underline') {
    return (
      <div className={`flex items-center gap-6 border-b border-slate-200 overflow-x-auto ${className}`}>
        {items.map((tab) => {
          const isActive = tab.id === activeId;
          return (
            <button
              key={tab.id}
              onClick={() => onChange(tab.id)}
              className={`pb-2.5 pt-1 text-xs font-medium border-b-2 whitespace-nowrap transition-colors flex items-center gap-1.5 cursor-pointer ${
                isActive
                  ? 'border-blue-600 text-blue-600 font-semibold'
                  : 'border-transparent text-slate-500 hover:text-slate-900 hover:border-slate-300'
              }`}
            >
              {tab.icon && <span className="shrink-0">{tab.icon}</span>}
              <span>{tab.label}</span>
              {tab.badge !== undefined && (
                <span
                  className={`text-[10px] px-1.5 py-0.2 rounded font-mono ${
                    isActive ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-slate-600'
                  }`}
                >
                  {tab.badge}
                </span>
              )}
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <div className={`inline-flex items-center p-0.5 bg-slate-100 border border-slate-200/80 rounded-md gap-0.5 ${className}`}>
      {items.map((tab) => {
        const isActive = tab.id === activeId;
        return (
          <button
            key={tab.id}
            onClick={() => onChange(tab.id)}
            className={`px-3 py-1.5 text-xs font-medium rounded transition-all whitespace-nowrap flex items-center gap-1.5 cursor-pointer select-none ${
              isActive
                ? 'bg-white text-slate-900 shadow-2xs font-semibold'
                : 'text-slate-600 hover:text-slate-900'
            }`}
          >
            {tab.icon && <span className="shrink-0">{tab.icon}</span>}
            <span>{tab.label}</span>
            {tab.badge !== undefined && (
              <span
                className={`text-[10px] px-1.5 py-0.2 rounded font-mono ${
                  isActive ? 'bg-slate-100 text-slate-800' : 'bg-slate-200 text-slate-600'
                }`}
              >
                {tab.badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
