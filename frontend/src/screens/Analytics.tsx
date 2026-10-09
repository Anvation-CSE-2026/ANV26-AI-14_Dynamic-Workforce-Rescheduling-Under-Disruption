// Operational analytics: are repairs working, what do they cost, who is absorbing disruptions.
import React from 'react';
import { api } from '../api/client';
import type { Analytics as A, Dashboard as D } from '../api/types';
import { Card, CardBody, CardHeader } from '../components/common/Card';
import { MetricCard } from '../components/common/MetricCard';
import { BarList, Gauge, TrendBars } from '../components/charts/Charts';
import { EmptyState, ErrorState, Spinner, useAsync } from '../components/common/States';
import { FairnessDistribution, OvertimeByPerson } from '../components/widgets/Widgets';
import { fmtNum } from '../lib/format';

export function Analytics({ refreshKey }: { refreshKey: number }) {
  const { loading, error, data, reload } = useAsync<A>(() => api.analytics(), [refreshKey]);
  const dash = useAsync<D>(() => api.dashboard(), [refreshKey]);
  if (loading && !data) return <Spinner />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;
  return (
    <div className="space-y-5">
      <section className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3" aria-label="Summary">
        <MetricCard label="Disruptions" value={data.disruptions} />
        <MetricCard label="Repairs approved" value={data.repairs_approved} subtext={data.repair_success_rate != null ? `${fmtNum(data.repair_success_rate)}% success` : undefined} />
        <MetricCard label="Avg impact" value={fmtNum(data.avg_impact_score)} unit={data.avg_impact_score != null ? '%' : undefined} subtext="Share of schedule touched" />
        <MetricCard label="Changes avoided" value={data.assignment_changes_avoided_vs_rebuild} subtext="vs. rebuilding from scratch" />
        <MetricCard label="Overtime avoided" value={fmtNum(data.overtime_hours_avoided)} unit="h" />
        <MetricCard label="Schedule stability" value={fmtNum(data.schedule_stability_pct)} unit="%" />
      </section>
      <div className="grid lg:grid-cols-3 gap-5">
        <Card className="lg:col-span-2">
          <CardHeader title="Disruptions vs repairs" />
          <CardBody className="p-4"><TrendBars data={data.trend} keys={[{ key: 'disruptions', label: 'Disruptions', className: 'bg-rose-400' }, { key: 'repairs', label: 'Repairs approved', className: 'bg-emerald-500' }]} /></CardBody>
        </Card>
        <Card>
          <CardHeader title="Health" />
          <CardBody className="p-4 flex justify-around">
            <Gauge value={data.skill_coverage_pct} label="Skill coverage" />
            <Gauge value={data.avg_fairness_score ?? 0} label="Avg fairness" tone="#7c3aed" />
          </CardBody>
          <CardBody className="px-4 pb-4 pt-0 text-xs text-slate-600 space-y-1">
            <p>Most common reason: <b>{data.most_common_disruption ?? '—'}</b></p>
            <p>Most affected area: <b>{data.most_affected_department ?? '—'}</b></p>
            <p>Avg people affected per repair: <b>{fmtNum(data.avg_employees_affected)}</b></p>
          </CardBody>
        </Card>
      </div>
      <div className="grid lg:grid-cols-2 gap-5">
        <Card>
          <CardHeader title="Impact of each approved repair" subtitle="Scheduling impact % per version" />
          <CardBody className="p-4">
            {data.repair_impact.length ? <BarList items={data.repair_impact.map((r) => ({ label: r.version, value: r.impact, sub: `· ${r.changes} chg · ${r.overtime}h OT` }))} unit="%" max={Math.max(10, ...data.repair_impact.map((r) => r.impact))} />
              : <p className="text-xs text-slate-500">Approve a repair to see its impact here.</p>}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Disruption reasons" />
          <CardBody className="p-4">
            {data.disruption_reasons.length ? <BarList items={data.disruption_reasons.map((r) => ({ label: r.reason, value: r.count }))} /> : <p className="text-xs text-slate-500">No disruptions yet.</p>}
          </CardBody>
        </Card>
        {dash.data && <FairnessDistribution data={dash.data.widgets} />}
        {dash.data && <OvertimeByPerson data={dash.data.widgets} />}
      </div>
      <OperationsFairness data={data} />
    </div>
  );
}

const num = (v: number | null | undefined) => (v === null || v === undefined ? '—' : fmtNum(v));

/** Operations & fairness: does ResQWork reduce disruption while keeping extra work fair? */
function OperationsFairness({ data }: { data: A }) {
  const fair = (data.fairness_distribution ?? []).map((r) => ({ label: r.employee, value: r.load }));
  const hours = (data.workload_distribution ?? []).map((r) => ({ label: r.employee, value: r.hours }));
  const rewards = (data.rewards_by_trigger ?? []).map((r) => ({ label: r.trigger.replace(/_/g, ' '), value: r.count }));
  const lv = data.notifications?.by_level;
  const levels = lv ? [{ label: 'Level 1 · Info', value: lv['1'] ?? 0 }, { label: 'Level 2 · Important', value: lv['2'] ?? 0 },
    { label: 'Level 3 · Critical', value: lv['3'] ?? 0 }].filter((x) => x.value > 0) : [];
  const chart = (title: string, items: { label: string; value: number }[], empty: string, caption?: string, unit?: string) => (
    <Card>
      <CardHeader title={title} subtitle={caption} />
      <CardBody className="p-4">{items.length ? <BarList items={items} unit={unit} /> : <EmptyState title={empty} />}</CardBody>
    </Card>
  );
  return (
    <section aria-label="Operations and fairness" className="space-y-3">
      <h2 className="text-sm font-semibold text-slate-900">Operations &amp; fairness</h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard label="Conflicts detected" value={num(data.conflicts_detected)} />
        <MetricCard label="Conflicts resolved" value={num(data.conflicts_resolved)} />
        <MetricCard label="Avg repair time" value={num(data.avg_repair_minutes)} unit={data.avg_repair_minutes != null ? 'min' : undefined} />
        <MetricCard label="Avg solve time" value={num(data.avg_solve_ms)} unit={data.avg_solve_ms != null ? 'ms' : undefined} />
        <MetricCard label="Staffing gaps" value={num(data.staffing_gaps)} subtext={`${num(data.staffing_gap_people)} people short`} />
        <MetricCard label="Volunteer participation" value={num(data.volunteer_participation)} />
        <MetricCard label="Hard-rule rejections" value={num(data.hard_constraint_rejections)} subtext="candidates rejected by hard rules; 0 published violations" />
        <MetricCard label="Soft-rule satisfaction" value={num(data.soft_constraint_satisfaction)} unit={data.soft_constraint_satisfaction != null ? '%' : undefined} />
      </div>
      <div className="grid lg:grid-cols-2 gap-5">
        {chart('Recent extra work by employee', fair, 'No fairness data yet', 'Lower is fairer; ResQWork asks people with less recent extra work first. Old contributions fade.')}
        {chart('Hours this week', hours, 'No scheduled hours yet', undefined, 'h')}
        {chart('Rewards by trigger', rewards, 'No rewards yet', 'Rewards are given only after completed work.')}
        {chart('Notifications by level', levels, 'No notifications yet')}
      </div>
    </section>
  );
}
