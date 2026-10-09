import type { KpiDef, MetricValue } from '../api/types';

export const fmtNum = (n: number | null | undefined, digits = 1) =>
  n === null || n === undefined || Number.isNaN(n) ? '—' : Number.isInteger(n) ? String(n) : n.toFixed(digits);

export function fmtKpi(def: Pick<KpiDef, 'format'>, v: MetricValue | undefined): { value: string; unit?: string } {
  if (!v || v.value === undefined) return { value: '—' };
  switch (def.format) {
    case 'percent': return { value: fmtNum(v.value), unit: '%' };
    case 'hours': return { value: fmtNum(v.value), unit: 'h' };
    case 'ratio': return { value: `${v.value}`, unit: v.total !== undefined ? `/ ${v.total}` : undefined };
    default: return { value: fmtNum(v.value, 0) };
  }
}

/** Is this KPI value in a healthy state, given whether higher or lower is better? */
export function kpiTone(def: Pick<KpiDef, 'good' | 'format'>, v: MetricValue | undefined): 'healthy' | 'warning' | 'critical' | 'neutral' {
  if (!v || v.value === undefined) return 'neutral';
  const x = def.format === 'ratio' && v.total ? (100 * v.value) / v.total : v.value;
  if (def.format === 'percent' || def.format === 'ratio') return x >= 98 ? 'healthy' : x >= 90 ? 'warning' : 'critical';
  if (def.good === 'low') return x === 0 ? 'healthy' : x <= 2 ? 'warning' : 'critical';
  return 'neutral';
}

// ---------------------------------------------------------------- dates & times: 24-hour clock everywhere
// Product rule: never AM/PM. Times are HH:MM (07:00, 17:30); date-times are "YYYY-MM-DD HH:MM".

const DAY = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: '2-digit', month: 'short' });
export const fmtDay = (iso: string) => DAY.format(new Date(`${iso}T00:00:00`));
export const fmtWeekday = (iso: string) => new Intl.DateTimeFormat('en-GB', { weekday: 'long' }).format(new Date(`${iso}T00:00:00`));
const pad = (n: number) => String(n).padStart(2, '0');

/** "2026-10-09 17:30" in the viewer's local time, 24-hour. Accepts ISO strings or epoch seconds. */
export const fmtWhen = (value: string | number | null | undefined): string => {
  if (value === null || value === undefined || value === '') return '—';
  const d = typeof value === 'number' ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

/** "HH:MM" normalisation for times coming from data ("7:00" → "07:00"). */
export const fmtTime = (hhmm?: string | null): string => {
  if (!hhmm) return '';
  const m = /^(\d{1,2}):(\d{2})/.exec(hhmm);
  return m ? `${pad(Number(m[1]))}:${m[2]}` : hhmm;
};

/** "07:00–15:00" (or "all day"). */
export const fmtRange = (start?: string | null, end?: string | null) =>
  start && end ? `${fmtTime(start)}–${fmtTime(end)}` : 'all day';

/** Validates a 24-hour time typed by a person. */
export const isHHMM = (v: string) => /^([01]\d|2[0-3]):[0-5]\d$/.test(v);

export const relative = (iso: string | null | undefined): string => {
  if (!iso) return '';
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return '';
  const m = Math.round(ms / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  return `${Math.round(h / 24)} d ago`;
};

export const titleCase = (s: string) => s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

export const REASON_LABEL: Record<string, string> = {
  REST_PERIOD_VIOLATION: 'Rest rule',
  SHIFT_OVERLAP: 'Already working',
  MISSING_SKILL: 'Missing skill',
  MISSING_CERTIFICATION: 'Missing certification',
  WOULD_UNCOVER_SHIFT: 'Opens another gap',
  SCHEDULE_CONFLICT: 'Schedule conflict',
  UNAVAILABLE: 'Unavailable',
  WOULD_CREATE_OVERTIME: 'Overtime',
  WOULD_EXCEED_MAX_HOURS: 'Hours limit',
  HIGHER_IMPACT: 'More disruption',
  EXCLUDED_BY_MANAGER: 'Excluded',
  LOCKED_BY_MANAGER: 'Locked',
  MANAGER_FEEDBACK: 'Your feedback',
};

export const impactTone = (level?: string): 'healthy' | 'warning' | 'critical' | 'neutral' =>
  level === 'LOW' ? 'healthy' : level === 'MEDIUM' ? 'warning' : level === 'HIGH' ? 'critical' : 'neutral';
