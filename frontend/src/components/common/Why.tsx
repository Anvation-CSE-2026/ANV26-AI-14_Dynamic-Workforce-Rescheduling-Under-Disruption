// Hover / focus reasoning. The text must come from real system data (solver evidence, formulas, records),
// never generic AI copy. Works with mouse, keyboard (focus) and touch (tap toggles).
import React, { useId, useState } from 'react';

export function Why({ text, children, className = '', side = 'top' }: {
  text?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  side?: 'top' | 'bottom';
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  if (!text) return <>{children}</>;
  return (
    <span className={`relative inline-flex ${className}`}
          onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}
          onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
          onClick={() => setOpen((o) => !o)}>
      <span tabIndex={0} aria-describedby={open ? id : undefined}
            className="cursor-help underline decoration-dotted decoration-slate-300 underline-offset-[3px] rounded-sm">
        {children}
      </span>
      {open && (
        <span role="tooltip" id={id}
              className={`absolute z-50 left-0 ${side === 'top' ? 'bottom-full mb-1.5' : 'top-full mt-1.5'} w-72 max-w-[80vw]
                          rounded-md bg-[#0E1B2C] text-white text-[11px] leading-snug font-normal normal-case tracking-normal
                          px-2.5 py-2 shadow-lg pointer-events-none text-left`}>
          {text}
        </span>
      )}
    </span>
  );
}
