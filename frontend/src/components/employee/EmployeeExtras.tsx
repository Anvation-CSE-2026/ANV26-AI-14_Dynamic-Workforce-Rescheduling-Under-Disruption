// Employee home additions: requests from admins, coverage/volunteer opportunities, critical alerts,
// Rewards & Recognition (points, badges, achievements, history) and a workload summary.
import { useState } from 'react';
import { api, errorMessage } from '../../api/client';
import type { AdminRequest, EmployeeHome, RequestAction } from '../../api/types';
import { Button } from '../common/Button';
import { Card, CardBody, CardHeader } from '../common/Card';
import { useAsync, usePoll } from '../common/States';
import { Chip, SeverityPill } from '../common/ui';
import { Award, Hand, Inbox, Scale, Star, Trophy } from '../common/icons';
import { fmtDay, fmtRange, fmtWhen, titleCase } from '../../lib/format';
import { useToast } from '../../lib/toast';

const ACTION_LABEL: Record<RequestAction, string> = { accept: 'Accept', decline: 'Decline', acknowledge: 'Acknowledge' };

export function EmployeeActions({ employeeId, onChanged }: { employeeId: string; onChanged: () => void }) {
  const toast = useToast();
  const { data, reload } = useAsync<EmployeeHome>(() => api.employeeHome(employeeId), [employeeId]);
  usePoll(reload, 10000);
  const [busy, setBusy] = useState<string | null>(null);
  if (!data) return null;
  const pending = data.admin_requests.filter((r) => r.my_status === 'pending' && r.status === 'open' && !r.workforce_request_id);
  const opps = data.opportunities.filter((o) => !o.my_status || o.my_status === 'volunteered' || o.my_status === 'approved');
  const critical = data.notifications.filter((n) => (n.severity ?? 1) >= 3 && !n.acknowledged_at);

  const respond = async (r: AdminRequest, a: RequestAction) => {
    setBusy(r.id);
    try { await api.respondAdminRequest(r.id, a); toast(`${ACTION_LABEL[a]}ed: ${r.title}`); reload(); onChanged(); } catch (e) { toast(errorMessage(e), 'error'); } finally { setBusy(null); }
  };
  const volunteer = async (id: string, accept: boolean) => {
    setBusy(id);
    try { await api.respondOpportunity(id, accept); toast(accept ? 'Thanks! Your admin will confirm. Volunteering alone does not assign you.' : 'Okay, not this time.', 'info'); reload(); onChanged(); }
    catch (e) { toast(errorMessage(e), 'error'); } finally { setBusy(null); }
  };
  if (!pending.length && !opps.length && !critical.length) return null;
  return (
    <section aria-label="Needs your response" className="space-y-3">
      {critical.map((n) => (
        <div key={n.id} className="rounded-lg border-2 border-rose-300 bg-rose-50 p-3 text-xs flex flex-wrap items-center justify-between gap-2" role="alert">
          <span><SeverityPill level={3} /> <b className="text-rose-900">{n.title}</b> <span className="text-rose-800">{n.message ?? n.body}</span></span>
          <Button size="sm" variant="primary" onClick={() => api.acknowledge(n.id).then(() => { reload(); onChanged(); }).catch((e) => toast(errorMessage(e), 'error'))}>Acknowledge</Button>
        </div>
      ))}
      {opps.length > 0 && (
        <Card className="border-[var(--accent)]">
          <CardHeader title={<span className="flex items-center gap-1.5"><Hand className="w-4 h-4 text-[var(--accent)]" />Coverage opportunities</span>} subtitle="Only shown to people who meet every requirement" />
          <ul className="divide-y divide-slate-100">{opps.map((o) => (
            <li key={o.id} className="p-3 flex flex-wrap items-center justify-between gap-2 text-xs">
              <span>{o.emergency && <Chip tone="red">emergency</Chip>} <b>{o.task}</b> · {fmtDay(o.date)} {fmtRange(o.start, o.end)}{o.location ? ` · ${o.location}` : ''}{o.skills.length ? ` · ${o.skills.join(', ')}` : ''}</span>
              {o.my_status === 'volunteered' ? <Chip tone="blue">You volunteered: waiting for admin</Chip> : o.my_status === 'approved' ? <Chip tone="green">Assigned to you</Chip> : (
                <span className="flex gap-1.5">
                  <Button size="sm" variant="action" disabled={busy === o.id} onClick={() => volunteer(o.id, true)}>Volunteer</Button>
                  <Button size="sm" variant="ghost" disabled={busy === o.id} onClick={() => volunteer(o.id, false)}>Not now</Button>
                </span>)}
            </li>))}</ul>
        </Card>
      )}
      {pending.length > 0 && (
        <Card>
          <CardHeader title={<span className="flex items-center gap-1.5"><Inbox className="w-4 h-4 text-slate-400" />Requests from your admin</span>} />
          <ul className="divide-y divide-slate-100">{pending.map((r) => (
            <li key={r.id} className="p-3 text-xs space-y-1.5">
              <p className="flex flex-wrap items-center gap-1.5"><SeverityPill level={r.severity} /><Chip>{titleCase(r.type)}</Chip><b>{r.title}</b></p>
              {r.message && <p className="text-slate-600">{r.message}</p>}
              <div className="flex gap-1.5">{r.actions.map((a) => (
                <Button key={a} size="sm" variant={a === 'decline' ? 'ghost' : 'primary'} disabled={busy === r.id} onClick={() => respond(r, a)}>{ACTION_LABEL[a]}</Button>))}</div>
            </li>))}</ul>
        </Card>
      )}
    </section>
  );
}

export function EmployeeRewardsCard({ employeeId }: { employeeId: string }) {
  const { data } = useAsync(() => api.employeeRewards(employeeId), [employeeId]);
  usePoll(() => undefined, 60000);
  if (!data) return null;
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-1.5"><Trophy className="w-4 h-4 text-amber-500" />Rewards & Recognition</span>}
                  subtitle="Earned when extra work is completed, never for simply volunteering" />
      <CardBody className="p-4 space-y-3 text-xs">
        <div className="flex items-end gap-4">
          <div><p className="text-2xl font-bold">{data.points_total}</p><p className="text-slate-500">points</p></div>
          <div><p className="text-lg font-semibold">{data.points_90d}</p><p className="text-slate-500">last 90 days</p></div>
          {data.tier && <Chip tone="violet"><Star className="w-3 h-3" />{data.tier.label}</Chip>}
        </div>
        <div className="flex flex-wrap gap-1.5">{data.badges.length ? data.badges.map((b) => <Chip key={b.id} tone="amber"><Award className="w-3 h-3" />{b.name}{b.count && b.count > 1 ? ` ×${b.count}` : ''}</Chip>) : <span className="text-slate-500">No badges yet</span>}</div>
        <ul className="space-y-1">{data.achievements.map((a) => (
          <li key={a.id} className="flex items-center gap-2"><span className={a.unlocked ? 'text-emerald-600' : 'text-slate-300'}>●</span><span className={a.unlocked ? 'font-medium' : 'text-slate-500'}>{a.name}</span><span className="text-slate-400">{a.progress}/{a.target}</span></li>))}</ul>
        {data.pending.length > 0 && <p className="text-slate-600">{data.pending.length} contribution(s) will be rewarded once completed.</p>}
        {data.history.length > 0 && <ul className="divide-y divide-slate-100 border-t border-slate-100">{data.history.slice(0, 5).map((h) => (
          <li key={h.id} className="py-1.5 flex justify-between gap-2"><span>{h.category_label}: {h.reason}</span><span className="whitespace-nowrap">+{h.points} · {fmtWhen(h.created_at)}</span></li>))}</ul>}
      </CardBody>
    </Card>
  );
}

export function WorkloadCard({ employeeId }: { employeeId: string }) {
  const { data } = useAsync<EmployeeHome>(() => api.employeeHome(employeeId), [employeeId]);
  if (!data) return null;
  const w = data.workload;
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-1.5"><Scale className="w-4 h-4 text-slate-400" />My workload</span>} subtitle={`Last ${w.window_days} days`} />
      <CardBody className="p-4 grid grid-cols-2 gap-2 text-xs">
        <p><span className="text-slate-500">This week</span><br /><b>{w.weekly_hours} h</b> of {w.contracted_weekly_hours} h</p>
        <p><span className="text-slate-500">This month</span><br /><b>{w.monthly_hours} h</b></p>
        <p><span className="text-slate-500">Extra assignments</span><br /><b>{w.additional_assignments}</b></p>
        <p><span className="text-slate-500">Volunteer covers</span><br /><b>{w.volunteer_assignments}</b> ({w.completed_volunteer_assignments} completed)</p>
      </CardBody>
    </Card>
  );
}
