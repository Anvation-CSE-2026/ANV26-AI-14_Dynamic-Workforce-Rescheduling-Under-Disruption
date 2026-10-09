// Small shared building blocks used by the admin and employee screens.
import React, { useId, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Info, Upload, XCircle } from './icons';
import { isHHMM } from '../../lib/format';
import type { Severity } from '../../api/types';

/** Page title row: what this screen is for, in one line, plus actions. */
export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
      <div className="min-w-0">
        <h2 className="text-lg font-semibold tracking-tight text-slate-900">{title}</h2>
        {subtitle && <p className="text-xs text-slate-500 mt-0.5 max-w-3xl">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Field({ label, hint, error, children, className = '' }: {
  label: string; hint?: string; error?: string | null; children: React.ReactElement | React.ReactNode; className?: string;
}) {
  return (
    <label className={`block text-xs text-slate-600 ${className}`}>
      <span className="font-medium text-slate-700">{label}</span>
      <div className="mt-1">{children}</div>
      {error ? <span className="block mt-1 text-rose-600" role="alert">{error}</span>
        : hint ? <span className="block mt-1 text-slate-400">{hint}</span> : null}
    </label>
  );
}

/** 24-hour time entry (HH:MM). Browser time pickers follow the OS locale and may show AM/PM, so this is a
 *  plain text field that only accepts 00:00–23:59. */
export function TimeInput({ value, onChange, id, required, ariaLabel, className = '' }: {
  value: string; onChange: (v: string) => void; id?: string; required?: boolean; ariaLabel?: string; className?: string;
}) {
  const [touched, setTouched] = useState(false);
  const bad = touched && value !== '' && !isHHMM(value);
  return (
    <input id={id} className={`input w-full font-mono ${bad ? 'border-rose-400' : ''} ${className}`} inputMode="numeric"
           placeholder="HH:MM" maxLength={5} pattern="([01][0-9]|2[0-3]):[0-5][0-9]" required={required}
           aria-label={ariaLabel} aria-invalid={bad || undefined} title="24-hour time, e.g. 07:00 or 17:30"
           value={value}
           onBlur={() => setTouched(true)}
           onChange={(e) => {
             let v = e.target.value.replace(/[^0-9:]/g, '');
             if (/^\d{3,4}$/.test(v)) v = `${v.slice(0, v.length - 2).padStart(2, '0')}:${v.slice(-2)}`;
             onChange(v.slice(0, 5));
           }} />
  );
}

export function SeverityPill({ level, label }: { level: Severity | undefined; label?: string }) {
  const l = level ?? 1;
  const cls = l === 3 ? 'bg-rose-50 text-rose-700 border-rose-200' : l === 2 ? 'bg-orange-50 text-orange-700 border-orange-200'
    : 'bg-emerald-50 text-emerald-700 border-emerald-200';
  const dot = l === 3 ? 'bg-rose-500' : l === 2 ? 'bg-orange-500' : 'bg-emerald-500';
  const text = label ?? (l === 3 ? 'Critical' : l === 2 ? 'Important' : 'Info');
  return (
    <span className={`inline-flex items-center gap-1.5 px-1.5 py-0.5 rounded border text-[10px] font-semibold uppercase tracking-wide ${cls}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${dot}`} aria-hidden />{text}
    </span>
  );
}

export function Chip({ children, tone = 'slate', className = '' }: { children: React.ReactNode; tone?: 'slate' | 'green' | 'amber' | 'red' | 'blue' | 'violet'; className?: string }) {
  const cls = { slate: 'bg-slate-100 text-slate-700', green: 'bg-emerald-50 text-emerald-700', amber: 'bg-amber-50 text-amber-800',
    red: 'bg-rose-50 text-rose-700', blue: 'bg-blue-50 text-blue-700', violet: 'bg-violet-50 text-violet-700' }[tone];
  return <span className={`inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded ${cls} ${className}`}>{children}</span>;
}

export function CheckRow({ ok, label, detail, warn }: { ok: boolean; label: string; detail?: string; warn?: boolean }) {
  return (
    <li className="flex items-start gap-2 text-xs">
      {ok && !warn ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 mt-px shrink-0" aria-label="pass" />
        : warn ? <AlertTriangle className="w-3.5 h-3.5 text-amber-600 mt-px shrink-0" aria-label="warning" />
          : <XCircle className="w-3.5 h-3.5 text-rose-600 mt-px shrink-0" aria-label="fail" />}
      <span><span className="font-medium text-slate-800">{label}</span>{detail && <span className="text-slate-500">: {detail}</span>}</span>
    </li>
  );
}

export function Avatar({ name, src, size = 32 }: { name?: string | null; src?: string | null; size?: number }) {
  const initials = (name ?? '?').split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join('') || '?';
  const style = { width: size, height: size, fontSize: Math.max(10, size / 2.8) };
  if (src) return <img src={src} alt="" className="rounded-full object-cover shrink-0 border border-slate-200" style={style} />;
  return (
    <span aria-hidden className="rounded-full shrink-0 grid place-items-center font-semibold text-white bg-[var(--accent)]" style={style}>
      {initials}
    </span>
  );
}

/** Drag-and-drop or click to pick a file. */
export function FileDrop({ accept, onFile, label, hint }: { accept: string; onFile: (f: File) => void; label: string; hint?: string }) {
  const ref = useRef<HTMLInputElement | null>(null);
  const [over, setOver] = useState(false);
  const id = useId();
  return (
    <div onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
         onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f) onFile(f); }}
         className={`rounded-lg border-2 border-dashed p-5 text-center transition-colors ${over ? 'border-[var(--accent)] bg-blue-50/40' : 'border-slate-200 bg-white'}`}>
      <Upload className="w-5 h-5 mx-auto text-slate-400" />
      <p className="text-xs text-slate-700 mt-2">
        <label htmlFor={id} className="font-semibold text-[var(--accent)] cursor-pointer hover:underline">{label}</label> or drop it here
      </p>
      {hint && <p className="text-[11px] text-slate-400 mt-1">{hint}</p>}
      <input id={id} ref={ref} type="file" accept={accept} className="sr-only"
             onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); if (ref.current) ref.current.value = ''; }} />
    </div>
  );
}

export function Notice({ tone = 'info', children }: { tone?: 'info' | 'warning' | 'error' | 'success'; children: React.ReactNode }) {
  const cls = { info: 'bg-blue-50 border-blue-200 text-blue-900', warning: 'bg-amber-50 border-amber-200 text-amber-900',
    error: 'bg-rose-50 border-rose-200 text-rose-900', success: 'bg-emerald-50 border-emerald-200 text-emerald-900' }[tone];
  const Icon = tone === 'success' ? CheckCircle2 : tone === 'info' ? Info : AlertTriangle;
  return (
    <div className={`flex items-start gap-2 rounded-md border px-3 py-2 text-xs ${cls}`} role={tone === 'error' ? 'alert' : 'status'}>
      <Icon className="w-4 h-4 shrink-0 mt-px" />
      <div className="min-w-0">{children}</div>
    </div>
  );
}

/** Tiny horizontal bar for workload / load comparisons. */
export function MiniBar({ value, max, tone = 'bg-[var(--accent)]' }: { value: number; max: number; tone?: string }) {
  const pct = max > 0 ? Math.min(100, (100 * value) / max) : 0;
  return (
    <span className="inline-block w-20 h-1.5 rounded bg-slate-100 align-middle overflow-hidden" aria-hidden>
      <span className={`block h-full ${tone}`} style={{ width: `${pct}%` }} />
    </span>
  );
}
