// Rewards & Recognition (admin): rewards are granted only for completed contributions, never for volunteering
// and never used by the scheduler. The original recognition board is kept as a tab.
import { useState } from 'react';
import { api, errorMessage } from '../api/client';
import type { RewardRule } from '../api/types';
import { Button } from '../components/common/Button';
import { Card, CardBody, CardHeader } from '../components/common/Card';
import { EmptyState, ErrorState, Spinner, useAsync } from '../components/common/States';
import { Tabs } from '../components/common/Tabs';
import { Chip, Field, Notice, PageHeader } from '../components/common/ui';
import { CheckCircle2, Star, Trophy } from '../components/common/icons';
import { fmtWhen } from '../lib/format';
import { useToast } from '../lib/toast';
import { Recognition } from './Recognition';

type Tab = 'overview' | 'rules' | 'recognition';

export function Rewards({ refreshKey, onChanged }: { refreshKey: number; onChanged: () => void }) {
  const toast = useToast();
  const [tab, setTab] = useState<Tab>('overview');
  const { data, loading, error, reload } = useAsync(() => api.rewards(), [refreshKey]);
  const [rules, setRules] = useState<RewardRule[] | null>(null);
  const [award, setAward] = useState({ employee_id: '', trigger: 'team_contribution' as 'team_contribution' | 'exceptional_performance', note: '' });

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    try { await fn(); toast(ok); reload(); onChanged(); } catch (e) { toast(errorMessage(e), 'error'); }
  };
  if (loading && !data) return <Spinner />;
  if (error || !data) return <ErrorState message={error ?? 'Unable to load rewards.'} onRetry={reload} />;
  const editRules = rules ?? data.config.rules;
  const badgeName = (id?: string | null) => data.config.badges.find((b) => b.id === id)?.name ?? id ?? '—';
  return (
    <div className="space-y-4">
      <PageHeader title="Rewards & Recognition" subtitle="Points, badges and achievements for successfully completed contributions. Volunteering alone earns nothing, and rewards never influence who gets scheduled." />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {[['Points (30 days)', data.stats.points_30d], ['Rewards issued', data.stats.rewards_issued], ['Badges issued', data.stats.badges_issued], ['Awaiting completion', data.stats.awaiting_completion]].map(([l, v]) => (
          <div key={String(l)} className="bg-white border border-slate-200 rounded-lg p-3"><p className="text-[11px] uppercase tracking-wide text-slate-500">{l}</p><p className="text-xl font-bold">{v}</p></div>
        ))}
      </div>
      <Tabs<Tab> items={[{ id: 'overview', label: 'Overview' }, { id: 'rules', label: 'Reward rules' }, { id: 'recognition', label: 'Recognition board' }]} activeId={tab} onChange={setTab} variant="underline" />
      {tab === 'overview' && (
        <div className="grid lg:grid-cols-2 gap-4">
          <Card>
            <CardHeader title="Awaiting your approval" subtitle="Completed contributions whose rule requires approval" />
            {!data.pending_approval.length ? <EmptyState title="Nothing to approve" /> : (
              <ul className="divide-y divide-slate-100 text-xs">{data.pending_approval.map((e) => (
                <li key={e.id} className="p-3 flex items-center justify-between gap-2"><span><b>{e.employee_name}</b> · {e.task} · +{e.points}</span>
                  <Button size="sm" variant="action" onClick={() => run(() => api.approveReward(e.id), 'Reward approved.')}>Approve</Button></li>))}</ul>
            )}
            <CardHeader title="Assigned, not yet completed" subtitle="Mark completed once the work is done" />
            {!data.pending_completion.length ? <EmptyState title="No open assignments" /> : (
              <ul className="divide-y divide-slate-100 text-xs">{data.pending_completion.slice(0, 15).map((e) => (
                <li key={e.id} className="p-3 flex items-center justify-between gap-2"><span><b>{e.employee_name}</b> · {e.task} · {e.date}</span>
                  <Button size="sm" icon={<CheckCircle2 className="w-3.5 h-3.5" />} onClick={() => run(() => api.completeEligibility(e.id), 'Marked completed.')}>Mark completed</Button></li>))}</ul>
            )}
          </Card>
          <Card>
            <CardHeader title="Leaderboard (90 days)" />
            <ul className="divide-y divide-slate-100 text-xs">{data.employees.filter((e) => e.points_total > 0).slice(0, 12).map((e, i) => (
              <li key={e.employee_id} className="p-3 flex items-center justify-between gap-2">
                <span className="flex items-center gap-2">{i < 3 ? <Trophy className="w-3.5 h-3.5 text-amber-500" /> : <span className="w-3.5 text-slate-400">{i + 1}</span>}<b>{e.employee_name}</b>{e.tier && <Chip>{e.tier.label}</Chip>}</span>
                <span>{e.points_90d} pts · {e.badges.length} badge(s)</span></li>))}
              {!data.employees.some((e) => e.points_total > 0) && <EmptyState title="No rewards yet" hint="Rewards appear when assigned coverage is completed." />}
            </ul>
            <CardHeader title="Give recognition" subtitle="Team contribution or exceptional performance" />
            <CardBody className="p-4 grid sm:grid-cols-2 gap-2">
              <Field label="Employee"><select className="input w-full" value={award.employee_id} onChange={(e) => setAward({ ...award, employee_id: e.target.value })}>
                <option value="">Choose…</option>{data.employees.map((e) => <option key={e.employee_id} value={e.employee_id}>{e.employee_name}</option>)}</select></Field>
              <Field label="Type"><select className="input w-full" value={award.trigger} onChange={(e) => setAward({ ...award, trigger: e.target.value as typeof award.trigger })}>
                <option value="team_contribution">Team contribution</option><option value="exceptional_performance">Exceptional performance</option></select></Field>
              <Field label="What it's for" className="sm:col-span-2"><input className="input w-full" value={award.note} onChange={(e) => setAward({ ...award, note: e.target.value })} /></Field>
              <Button variant="primary" icon={<Star className="w-3.5 h-3.5" />} disabled={!award.employee_id || !award.note.trim()}
                      onClick={() => run(() => api.giveReward(award.employee_id, award.trigger, award.note), 'Recognition given.').then(() => setAward({ ...award, note: '' }))}>Give recognition</Button>
            </CardBody>
          </Card>
          <Card className="lg:col-span-2">
            <CardHeader title="Recent rewards" />
            <ul className="divide-y divide-slate-100 text-xs">{data.recent.map((a) => (
              <li key={a.id} className="p-3 flex flex-wrap justify-between gap-2"><span><b>{a.employee_name}</b> · {a.category_label} · {a.reason}</span>
                <span>+{a.points}{a.badge ? ` · ${badgeName(a.badge)}` : ''} · {fmtWhen(a.created_at)}</span></li>))}</ul>
          </Card>
        </div>
      )}
      {tab === 'rules' && (
        <Card>
          <CardHeader title="Reward rules" subtitle="Applied when an assignment is completed" action={<Button size="sm" variant="primary" disabled={!rules}
            onClick={() => run(() => api.saveRewardRules(editRules), 'Reward rules saved.').then(() => setRules(null))}>Save rules</Button>} />
          <Notice tone="info">Rewards are only checked after successful completion. Clicking “Volunteer” never earns points.</Notice>
          <div className="overflow-x-auto"><table className="w-full text-xs text-left">
            <thead className="text-[11px] uppercase text-slate-500 bg-slate-50"><tr><th className="px-3 py-2">Trigger</th><th className="px-2">Label</th><th className="px-2">Points</th><th className="px-2">Badge</th><th className="px-2">Needs approval</th><th className="px-2">Enabled</th></tr></thead>
            <tbody>{editRules.map((r, i) => {
              const set = (b: Partial<RewardRule>) => setRules(editRules.map((x, j) => (j === i ? { ...x, ...b } : x)));
              return (
                <tr key={r.id} className="border-t border-slate-100">
                  <td className="px-3 py-2">{data.triggers[r.trigger] ?? r.trigger}</td>
                  <td className="px-2"><input aria-label="Label" className="input w-44" value={r.label} onChange={(e) => set({ label: e.target.value })} /></td>
                  <td className="px-2"><input aria-label="Points" className="input w-20" inputMode="numeric" value={r.points} onChange={(e) => set({ points: Number(e.target.value) || 0 })} /></td>
                  <td className="px-2"><select aria-label="Badge" className="input" value={r.badge ?? ''} onChange={(e) => set({ badge: e.target.value || null })}>
                    <option value="">None</option>{data.config.badges.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select></td>
                  <td className="px-2"><input type="checkbox" aria-label="Requires approval" checked={r.requires_approval} onChange={(e) => set({ requires_approval: e.target.checked })} /></td>
                  <td className="px-2"><input type="checkbox" aria-label="Enabled" checked={r.enabled} onChange={(e) => set({ enabled: e.target.checked })} /></td>
                </tr>);
            })}</tbody>
          </table></div>
        </Card>
      )}
      {tab === 'recognition' && <Recognition refreshKey={refreshKey} />}
    </div>
  );
}
