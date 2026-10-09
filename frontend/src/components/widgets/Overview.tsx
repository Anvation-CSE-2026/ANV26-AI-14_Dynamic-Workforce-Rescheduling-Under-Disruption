// Admin overview strip: what is going wrong, what needs attention, and the state of workforce, notifications,
// fairness and rewards, each linking to the screen where the admin acts on it.
import type { ReactNode } from 'react';
import type { AdminOverview } from '../../api/types';
import { AlertTriangle, Award, Bell, Cpu, Scale, UserPlus, Wrench } from '../common/icons';
import { Chip, MiniBar } from '../common/ui';
import { fmtDay, fmtRange } from '../../lib/format';

export type OverviewTarget = 'conflicts' | 'repair_center' | 'workforce' | 'notifications' | 'recognition' | 'employees' | 'constraints';

export function Overview({ o, onNavigate }: { o: AdminOverview; onNavigate?: (t: OverviewTarget) => void }) {
  const tiles: { t: OverviewTarget; label: string; value: number | string; sub: string; icon: ReactNode; alert?: boolean }[] = [
    { t: 'repair_center', label: 'Pending repairs', value: o.repairs.pending, sub: `${o.repairs.critical_disruptions} critical disruption(s)`, icon: <Wrench className="w-4 h-4" />, alert: o.repairs.critical_disruptions > 0 },
    { t: 'workforce', label: 'Staffing gaps', value: o.staffing_gaps.length, sub: `${o.staffing_gaps.reduce((a, g) => a + g.gap, 0)} people short`, icon: <UserPlus className="w-4 h-4" />, alert: o.staffing_gaps.length > 0 },
    { t: 'workforce', label: 'Workforce requests', value: o.workforce.open, sub: `${o.workforce.volunteers} volunteer(s) · ${o.workforce.completed} completed`, icon: <UserPlus className="w-4 h-4" /> },
    { t: 'notifications', label: 'Awaiting acknowledgement', value: o.notifications.awaiting_acknowledgement, sub: `${o.notifications.escalated} escalated · ${o.notifications.by_level['3'] ?? 0} critical`, icon: <Bell className="w-4 h-4" /> },
    { t: 'recognition', label: 'Rewards (30 days)', value: `${o.rewards.points_30d} pts`, sub: `${o.rewards.awaiting_completion} awaiting completion`, icon: <Award className="w-4 h-4" /> },
  ];
  const maxLoad = Math.max(1, ...o.fairness.map((f) => f.contribution_load));
  return (
    <section aria-label="Operations overview" className="space-y-3">
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3">
        {tiles.map((x) => (
          <button key={x.label} onClick={() => onNavigate?.(x.t)} className={`text-left bg-white border rounded-lg p-3 hover:border-slate-300 transition-colors ${x.alert ? 'border-rose-200' : 'border-slate-200'}`}>
            <div className="flex items-center justify-between text-[11px] uppercase tracking-wide text-slate-500">{x.label}<span className={x.alert ? 'text-rose-500' : 'text-slate-400'}>{x.icon}</span></div>
            <p className="text-xl font-bold text-slate-900 mt-1">{x.value}</p>
            <p className="text-[11px] text-slate-500 truncate">{x.sub}</p>
          </button>
        ))}
      </div>
      <div className="grid lg:grid-cols-3 gap-3">
        <div className="bg-white border border-slate-200 rounded-lg p-3 lg:col-span-1">
          <p className="text-xs font-semibold text-slate-800 flex items-center gap-1.5"><AlertTriangle className="w-3.5 h-3.5 text-amber-500" />Staffing gaps</p>
          {!o.staffing_gaps.length ? <p className="text-xs text-slate-500 mt-2">Every task has the people it needs.</p> : (
            <ul className="mt-2 space-y-1 text-xs">{o.staffing_gaps.slice(0, 4).map((g) => (
              <li key={g.id}><Chip tone={g.priority === 'critical' ? 'red' : 'amber'}>{g.gap} short</Chip> {g.task} · {fmtDay(g.date)} {fmtRange(g.start, g.end)}</li>))}</ul>
          )}
        </div>
        <div className="bg-white border border-slate-200 rounded-lg p-3">
          <p className="text-xs font-semibold text-slate-800 flex items-center gap-1.5"><Scale className="w-3.5 h-3.5 text-slate-400" />Workload fairness (recent extra work)</p>
          <ul className="mt-2 space-y-1 text-xs">{o.fairness.slice(0, 5).map((f) => (
            <li key={f.employee_id} className="flex items-center justify-between gap-2"><span className="truncate">{f.employee_name}</span><span className="whitespace-nowrap"><MiniBar value={f.contribution_load} max={maxLoad} /> {f.contribution_load}</span></li>))}</ul>
        </div>
        <button onClick={() => onNavigate?.('constraints')} className="text-left bg-white border border-slate-200 rounded-lg p-3 hover:border-slate-300">
          <p className="text-xs font-semibold text-slate-800 flex items-center gap-1.5"><Cpu className="w-3.5 h-3.5 text-slate-400" />Optimizer</p>
          <p className="text-sm font-semibold mt-1">{o.solver.engine}</p>
          <p className="text-[11px] text-slate-500 mt-1">{o.solver.message}</p>
          <p className="text-[11px] text-slate-500 mt-1">{o.employees.active} active · {o.employees.inactive} inactive employees</p>
        </button>
      </div>
    </section>
  );
}
