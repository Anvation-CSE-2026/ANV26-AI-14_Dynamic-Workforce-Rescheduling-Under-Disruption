// The live schedule. Changed and disrupted assignments are highlighted; everything else is unchanged.
import React, { useMemo, useState } from 'react';
import { Search } from '../components/common/icons';
import { api } from '../api/client';
import type { ScheduleRow } from '../api/types';
import { Card } from '../components/common/Card';
import { EmptyState, ErrorState, Spinner, useAsync } from '../components/common/States';
import { useDomain } from '../lib/domain';
import { Why } from '../components/common/Why';
import { fmtDay } from '../lib/format';

const STATUS: Record<ScheduleRow['status'], { label: string; cls: string }> = {
  scheduled: { label: 'Scheduled', cls: 'text-slate-500' },
  open: { label: 'Open', cls: 'text-amber-700 bg-amber-50 border-amber-200' },
  disrupted: { label: 'At risk', cls: 'text-rose-700 bg-rose-50 border-rose-200' },
  changed: { label: 'Changed', cls: 'text-emerald-700 bg-emerald-50 border-emerald-200' },
};

export function Schedule({ refreshKey }: { refreshKey: number }) {
  const { t } = useDomain();
  const { loading, error, data, reload } = useAsync<ScheduleRow[]>(() => api.schedule(), [refreshKey]);
  const [dept, setDept] = useState('');
  const [q, setQ] = useState('');
  const [only, setOnly] = useState(false);

  const rows = useMemo(() => (data ?? []).filter((r) =>
    (!dept || r.department === dept) && (!only || r.status !== 'scheduled') &&
    (!q || `${r.assignment} ${r.employee_name ?? ''} ${r.original_employee_name ?? ''}`.toLowerCase().includes(q.toLowerCase()))), [data, dept, q, only]);
  const depts = useMemo(() => [...new Set((data ?? []).map((r) => r.department).filter(Boolean))] as string[], [data]);
  const byDay = useMemo(() => {
    const m = new Map<string, ScheduleRow[]>();
    rows.forEach((r) => m.set(r.date, [...(m.get(r.date) ?? []), r]));
    return [...m.entries()];
  }, [rows]);

  if (loading && !data) return <Spinner />;
  if (error) return <ErrorState message={error} onRetry={reload} />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2 items-center">
        <div className="relative">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-slate-400" />
          <input aria-label="Search schedule" className="input pl-8 w-64" placeholder={`Search ${t('employee', 'person').toLowerCase()} or ${t('shift', 'shift').toLowerCase()}`} value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <select aria-label={t('department', 'Department')} className="input" value={dept} onChange={(e) => setDept(e.target.value)}>
          <option value="">All {t('departments', 'departments').toLowerCase()}</option>
          {depts.map((d) => <option key={d}>{d}</option>)}
        </select>
        <label className="text-xs text-slate-600 flex items-center gap-1.5"><input type="checkbox" checked={only} onChange={(e) => setOnly(e.target.checked)} /> Only changes & risks</label>
        <span className="text-xs text-slate-500 ml-auto">{rows.length} {t('shifts', 'shifts').toLowerCase()}</span>
      </div>
      {byDay.length === 0 ? <Card><EmptyState title="Nothing matches" /></Card> : byDay.map(([day, list]) => (
        <Card key={day}>
          <div className="px-4 py-2 border-b border-slate-100 text-xs font-semibold text-slate-700 bg-slate-50/60">{fmtDay(day)}</div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-slate-500"><tr>
                <th className="text-left font-medium px-4 py-1.5 w-28">Time</th>
                <th className="text-left font-medium px-2">{t('shift', 'Shift')}</th>
                <th className="text-left font-medium px-2">{t('department', 'Department')}</th>
                <th className="text-left font-medium px-2">{t('employee', 'Assigned')}</th>
                <th className="text-left font-medium px-2">{t('skills', 'Skills')}</th>
                <th className="text-left font-medium px-4">Status</th>
              </tr></thead>
              <tbody>{list.map((r) => {
                const s = STATUS[r.status];
                return (
                  <tr key={r.shift_id} className={`border-t border-slate-100 ${r.status === 'changed' ? 'bg-emerald-50/40' : r.status === 'disrupted' ? 'bg-rose-50/40' : ''}`}>
                    <td className="px-4 py-2 tabular-nums text-slate-600 whitespace-nowrap">{r.start}–{r.end}</td>
                    <td className="px-2">{r.assignment}{r.priority === 'critical' && <span className="ml-1.5 text-[10px] text-rose-600 uppercase">critical</span>}</td>
                    <td className="px-2 text-slate-600">{r.department}</td>
                    <td className="px-2">
                      {r.status === 'changed' && r.original_employee_name && <span className="line-through text-slate-400 mr-1.5">{r.original_employee_name}</span>}
                      <span className={r.status === 'disrupted' ? 'line-through text-rose-600' : 'font-medium'}>{r.employee_name ?? '—'}</span>
                    </td>
                    <td className="px-2 text-slate-500">{r.required_skills.join(', ')}</td>
                    <td className="px-4">{r.status === 'scheduled' ? <span className={s.cls}>{s.label}</span> : (
                      <Why text={r.status === 'changed' ? `Changed by an approved repair: ${r.original_employee_name ?? 'nobody'} was assigned before, ${r.employee_name ?? 'nobody'} works it now.`
                        : r.status === 'disrupted' ? `${r.employee_name} is unavailable for this ${t('shift', 'shift').toLowerCase()} (open disruption). It needs a repair before it starts.`
                        : 'Nobody is assigned; mandatory coverage is not met.'}>
                        <span className={`px-1.5 py-0.5 rounded border ${s.cls}`}>{s.label}</span></Why>)}</td>
                  </tr>
                );
              })}</tbody>
            </table>
          </div>
        </Card>
      ))}
    </div>
  );
}
