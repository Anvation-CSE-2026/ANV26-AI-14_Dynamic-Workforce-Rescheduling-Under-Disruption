// Lightweight, dependency-free SVG/HTML charts (accessible: every chart has a text/table equivalent via title + labels).
import React from 'react';

export function BarList({ items, max, unit = '', tone = 'bg-[var(--accent)]', marker }: {
  items: { label: string; value: number; sub?: string; danger?: boolean }[];
  max?: number;
  unit?: string;
  tone?: string;
  marker?: number;
}) {
  const top = max ?? Math.max(1, ...items.map((i) => i.value), marker ?? 0);
  return (
    <ul className="space-y-1.5" role="list">
      {items.map((i) => (
        <li key={i.label} className="grid grid-cols-[minmax(0,9rem)_1fr_auto] items-center gap-2 text-xs">
          <span className="truncate text-slate-600" title={i.label}>{i.label}</span>
          <span className="relative h-2.5 bg-slate-100 rounded" aria-hidden>
            <span className={`absolute inset-y-0 left-0 rounded ${i.danger ? 'bg-rose-500' : tone}`} style={{ width: `${Math.min(100, (100 * i.value) / top)}%` }} />
            {marker !== undefined && <span className="absolute -inset-y-0.5 w-px bg-slate-500" style={{ left: `${(100 * marker) / top}%` }} />}
          </span>
          <span className="tabular-nums font-medium text-slate-800 w-16 text-right">{Number.isInteger(i.value) ? i.value : i.value.toFixed(1)}{unit}{i.sub && <span className="text-slate-400 font-normal"> {i.sub}</span>}</span>
        </li>
      ))}
    </ul>
  );
}

export function StackedBar({ segments, height = 10 }: { segments: { value: number; className: string; label: string }[]; height?: number }) {
  const total = segments.reduce((a, s) => a + s.value, 0) || 1;
  return (
    <div className="flex w-full overflow-hidden rounded" style={{ height }} role="img"
         aria-label={segments.map((s) => `${s.label}: ${s.value}`).join(', ')}>
      {segments.map((s) => (
        <div key={s.label} className={s.className} style={{ width: `${(100 * s.value) / total}%` }} title={`${s.label}: ${s.value}`} />
      ))}
    </div>
  );
}

export function Gauge({ value, label, tone = '#0f766e' }: { value: number; label: string; tone?: string }) {
  const r = 34, c = 2 * Math.PI * r, v = Math.max(0, Math.min(100, value));
  return (
    <figure className="flex flex-col items-center" aria-label={`${label}: ${v}`}>
      <svg width="88" height="88" viewBox="0 0 88 88" role="img">
        <circle cx="44" cy="44" r={r} fill="none" stroke="#e2e8f0" strokeWidth="8" />
        <circle cx="44" cy="44" r={r} fill="none" stroke={tone} strokeWidth="8" strokeLinecap="round"
                strokeDasharray={`${(c * v) / 100} ${c}`} transform="rotate(-90 44 44)" />
        <text x="44" y="49" textAnchor="middle" className="fill-slate-900" style={{ fontSize: 18, fontWeight: 700 }}>{Math.round(v)}</text>
      </svg>
      <figcaption className="text-[11px] text-slate-500 -mt-1">{label}</figcaption>
    </figure>
  );
}

export function TrendBars({ data, keys }: { data: Record<string, any>[]; keys: { key: string; label: string; className: string }[] }) {
  const max = Math.max(1, ...data.flatMap((d) => keys.map((k) => d[k.key] ?? 0)));
  if (!data.length) return <p className="text-xs text-slate-500">No history yet.</p>;
  return (
    <div>
      <div className="flex items-end gap-3 h-32 border-b border-slate-200 px-1" role="img" aria-label="Trend chart">
        {data.map((d, i) => (
          <div key={i} className="flex-1 flex flex-col items-center gap-1 min-w-0">
            <div className="flex items-end gap-0.5 h-28 w-full justify-center">
              {keys.map((k) => (
                <div key={k.key} className={`${k.className} w-3 rounded-t`} style={{ height: `${(100 * (d[k.key] ?? 0)) / max}%` }} title={`${k.label}: ${d[k.key] ?? 0}`} />
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="flex gap-3 px-1 mt-1">
        {data.map((d, i) => <span key={i} className="flex-1 text-center text-[10px] text-slate-500 truncate">{d.date ?? d.version}</span>)}
      </div>
      <div className="flex gap-3 mt-2">
        {keys.map((k) => <span key={k.key} className="flex items-center gap-1 text-[11px] text-slate-600"><span className={`w-2.5 h-2.5 rounded-sm ${k.className}`} />{k.label}</span>)}
      </div>
    </div>
  );
}
