// Generic dashboard widgets. Domain configs choose which ones each sub-dashboard shows and what they're called.
import React from 'react';
import { AlertTriangle, ShieldCheck } from '../common/icons';
import type { Dashboard, PolicyOverview, ScheduleRow } from '../../api/types';
import { api } from '../../api/client';
import { Card, CardBody, CardHeader } from '../common/Card';
import { BarList, StackedBar } from '../charts/Charts';
import { useDomain } from '../../lib/domain';
import { EmptyState, Spinner, useAsync } from '../common/States';
import { fmtDay, titleCase } from '../../lib/format';

type W = Dashboard['widgets'];

export function DepartmentCoverage({ data }: { data: W }) {
  const { t } = useDomain();
  const rows = data.department_coverage ?? [];
  return (
    <Card>
      <CardHeader title={`${t('department', 'Department')} coverage`} subtitle="Upcoming shifts: covered · at risk · open" />
      <CardBody className="p-4 space-y-3">
        {rows.map((r) => (
          <div key={r.department}>
            <div className="flex justify-between text-xs mb-1">
              <span className="font-medium text-slate-700">{r.department}</span>
              <span className="tabular-nums text-slate-500">{r.covered}/{r.total}{r.at_risk ? <span className="text-rose-600 font-medium"> · {r.at_risk} at risk</span> : null}</span>
            </div>
            <StackedBar segments={[{ value: r.covered, className: 'bg-emerald-500', label: 'Covered' },
                                   { value: r.at_risk, className: 'bg-rose-500', label: 'At risk' },
                                   { value: Math.max(0, r.total - r.covered - r.at_risk), className: 'bg-slate-200', label: 'Open' }]} />
          </div>
        ))}
      </CardBody>
    </Card>
  );
}

export function QualificationMatrix({ data }: { data: W }) {
  const { t } = useDomain();
  const rows = (data.qualification_matrix ?? []).filter((r) => r.demand > 0);
  return (
    <Card>
      <CardHeader title={`${t('skills', 'Skills')}: demand vs holders`} subtitle="Few holders = single point of failure" />
      <CardBody className="p-4">
        {rows.length ? (
          <table className="w-full text-xs">
            <thead><tr className="text-slate-500"><th className="text-left font-medium pb-1">{t('skill', 'Skill')}</th><th className="text-right font-medium">Shifts needing it</th><th className="text-right font-medium">People holding it</th></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.skill} className="border-t border-slate-100">
                <td className="py-1.5">{r.skill}</td>
                <td className="text-right tabular-nums">{r.demand}</td>
                <td className={`text-right tabular-nums font-medium ${r.holders <= 2 ? 'text-rose-600' : 'text-slate-800'}`}>{r.holders}</td>
              </tr>))}
            </tbody>
          </table>
        ) : <EmptyState title="No skill requirements" />}
      </CardBody>
    </Card>
  );
}

export function FatigueRisk({ data }: { data: W }) {
  const rows = data.fatigue_risk ?? [];
  return (
    <Card>
      <CardHeader title="Fatigue & load risk" subtitle="Short rest or at/over contracted hours" />
      <CardBody className="p-0">
        {rows.length ? (
          <ul className="divide-y divide-slate-100 text-xs">
            {rows.slice(0, 8).map((r, i) => (
              <li key={i} className="px-4 py-2 flex items-start gap-2"><AlertTriangle className="w-3.5 h-3.5 text-amber-500 mt-0.5 shrink-0" />
                <span><b className="font-medium text-slate-800">{r.employee}</b> <span className="text-slate-500">· {r.reason}</span></span></li>
            ))}
          </ul>
        ) : <EmptyState title="No fatigue risks" />}
      </CardBody>
    </Card>
  );
}

export function OvertimeByPerson({ data }: { data: W }) {
  const rows = (data.overtime_by_person ?? []).filter((r) => r.hours > 0).slice(0, 10);
  return (
    <Card>
      <CardHeader title="Hours this week" subtitle="Bar = scheduled hours; line = contracted hours" />
      <CardBody className="p-4">
        <BarList items={rows.map((r) => ({ label: r.employee, value: r.hours, danger: r.overtime > 0, sub: r.overtime ? `+${r.overtime} OT` : undefined }))}
                 unit="h" marker={rows[0]?.contracted} />
      </CardBody>
    </Card>
  );
}

export function WorkloadBalance({ data }: { data: W }) {
  const rows = [...(data.workload_balance ?? [])].sort((a, b) => b.hours - a.hours).slice(0, 12);
  return (
    <Card>
      <CardHeader title="Workload balance" subtitle="Scheduled hours this week" />
      <CardBody className="p-4"><BarList items={rows.map((r) => ({ label: r.employee, value: r.hours }))} unit="h" /></CardBody>
    </Card>
  );
}

export function FairnessDistribution({ data }: { data: W }) {
  const rows = [...(data.fairness_distribution ?? [])].sort((a, b) =>
    (b.disruptions_absorbed_30d * 2 + b.schedule_changes_30d) - (a.disruptions_absorbed_30d * 2 + a.schedule_changes_30d)).slice(0, 10);
  return (
    <Card>
      <CardHeader title="Disruption burden (30 days)" subtitle="Who has absorbed short-notice changes; used by the fairness objective" />
      <CardBody className="p-4">
        <BarList items={rows.map((r) => ({ label: r.employee, value: r.disruptions_absorbed_30d, sub: `· ${r.schedule_changes_30d} changes`, danger: r.disruptions_absorbed_30d >= 3 }))} max={5} />
      </CardBody>
    </Card>
  );
}

export function DisruptionHistory({ data }: { data: W }) {
  const rows = data.disruption_history ?? [];
  return (
    <Card>
      <CardHeader title="Disruption history" />
      <CardBody className="p-0">
        {rows.length ? (
          <ul className="divide-y divide-slate-100 text-xs">
            {rows.slice(0, 10).map((r, i) => (
              <li key={i} className="px-4 py-2 flex justify-between gap-2">
                <span><b className="font-medium">{r.employee}</b> <span className="text-slate-500">· {r.reason ?? 'unspecified'} · {r.source}</span></span>
                <span className={`capitalize ${r.status === 'open' ? 'text-rose-600' : 'text-emerald-700'}`}>{r.status}</span>
              </li>
            ))}
          </ul>
        ) : <EmptyState title="No disruptions recorded yet" hint="Simulate one from the command center." />}
      </CardBody>
    </Card>
  );
}

export function Compliance() {
  const { loading, data } = useAsync<PolicyOverview>(() => api.policies());
  return (
    <Card>
      <CardHeader title="Policy compliance" subtitle="Rules retrieved from your policy documents" />
      <CardBody className="p-0">
        {loading ? <Spinner /> : (
          <ul className="divide-y divide-slate-100 text-xs">
            {(data?.constraints ?? []).filter((c) => c.severity === 'hard').slice(0, 8).map((c, i) => (
              <li key={i} className="px-4 py-2 flex items-start gap-2"><ShieldCheck className="w-3.5 h-3.5 text-emerald-600 mt-0.5 shrink-0" />
                <span><b className="font-medium">{titleCase(c.type)}</b>: {String(c.value)}{c.unit ? ` ${c.unit}` : ''} <span className="text-slate-500">· {c.source}</span></span></li>
            ))}
            {data?.conflicts.map((c, i) => <li key={`c${i}`} className="px-4 py-2 text-amber-700 flex gap-2"><AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />{c}</li>)}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}

export function Roster() {
  const { t } = useDomain();
  const { loading, data } = useAsync<ScheduleRow[]>(() => api.schedule());
  if (loading) return <Card><Spinner /></Card>;
  const days = [...new Set((data ?? []).map((r) => r.date))].slice(-2);
  const rows = (data ?? []).filter((r) => days.includes(r.date));
  return (
    <Card>
      <CardHeader title={`${t('shift', 'Shift')} roster`} subtitle={days.map(fmtDay).join(' · ')} />
      <CardBody className="p-0 max-h-80 overflow-auto">
        <table className="w-full text-xs">
          <tbody>{rows.map((r) => (
            <tr key={r.shift_id} className="border-t border-slate-100">
              <td className="px-4 py-1.5 whitespace-nowrap text-slate-500">{fmtDay(r.date)} {r.start}</td>
              <td className="px-2 truncate max-w-[12rem]" title={r.assignment}>{r.assignment}</td>
              <td className={`px-2 font-medium ${r.status === 'disrupted' ? 'text-rose-600 line-through' : r.status === 'changed' ? 'text-emerald-700' : ''}`}>{r.employee_name ?? '—'}</td>
            </tr>))}
          </tbody>
        </table>
      </CardBody>
    </Card>
  );
}

export const WIDGETS: Record<string, React.ComponentType<{ data: W }>> = {
  department_coverage: DepartmentCoverage,
  qualification_matrix: QualificationMatrix,
  fatigue_risk: FatigueRisk,
  overtime_by_person: OvertimeByPerson,
  workload_balance: WorkloadBalance,
  fairness_distribution: FairnessDistribution,
  disruption_history: DisruptionHistory,
  compliance: () => <Compliance />,
  roster: () => <Roster />,
};
