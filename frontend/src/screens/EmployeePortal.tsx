// Employee dashboard. Answers, in order: What am I working on? What changed? Do I need to act?
// What's pending? What have I been recognized for? Polls so manager decisions show up without reloading.
import React, { useMemo, useState } from 'react';
import { Award as AwardIcon, Bell, CalendarDays, CheckCircle2, LogOut, Plus, Volume2, ArrowRight, AlertTriangle } from '../components/common/icons';
import { api, errorMessage } from '../api/client';
import type { EmployeeView, RecognitionConfig, RecognitionSummary, RequestKind, User, WorkspaceSummary } from '../api/types';
import { Button } from '../components/common/Button';
import { Card, CardBody, CardHeader } from '../components/common/Card';
import { Modal } from '../components/common/Modal';
import { EmptyState, ErrorState, Spinner, useAsync, usePoll } from '../components/common/States';
import { Why } from '../components/common/Why';
import { DemoSwitcher } from '../components/layout/DemoSwitcher';
import { useDomain } from '../lib/domain';
import { fmtDay, fmtWhen } from '../lib/format';
import { canSpeak, speak } from '../lib/speech';
import { useToast } from '../lib/toast';
import { REQUEST_KIND } from './Dashboard';
import { StatusPill } from './Requests';
import { Profile } from './Profile';
import { EmployeeActions, EmployeeRewardsCard, WorkloadCard } from '../components/employee/EmployeeExtras';
import { Avatar, TimeInput } from '../components/common/ui';

export function EmployeePortal({ user, workspace, onLogout, onSwitched }: {
  user: User; workspace: WorkspaceSummary; onLogout: () => void; onSwitched: (u: User, token: string) => void;
}) {
  const { config, t } = useDomain();
  const toast = useToast();
  const { loading, error, data, reload } = useAsync<EmployeeView>(() => api.employeeView(user.employee_id!), [user.employee_id]);
  const rec = useAsync<RecognitionSummary & { config: RecognitionConfig }>(() => api.employeeRecognition(user.employee_id!), [user.employee_id]);
  usePoll(reload, 8000);
  usePoll(rec.reload, 15000);
  const [formOpen, setFormOpen] = useState(false);
  const [view, setView] = useState<'home' | 'profile'>('home');

  const today = workspace.reference_date ?? data?.schedule[0]?.date;
  const upcoming = useMemo(() => (data?.schedule ?? []).filter((s) => !today || s.date >= today), [data, today]);
  const byDay = useMemo(() => {
    const m = new Map<string, typeof upcoming>();
    upcoming.forEach((s) => m.set(s.date, [...(m.get(s.date) ?? []), s]));
    return [...m.entries()];
  }, [upcoming]);

  if (!user.employee_id) return <ErrorState message="This account is not linked to an employee record." />;
  if (loading && !data) return <div className="min-h-screen grid place-items-center"><Spinner /></div>;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;

  const toAck = data.notifications.filter((n) => n.requires_acknowledgement && !n.acknowledged_at);
  const openReqs = data.requests.filter((r) => ['pending', 'needs_review', 'approved'].includes(r.status));
  const next = upcoming.find((s) => s.status !== 'disrupted');
  const imOut = upcoming.filter((s) => s.status === 'disrupted');
  const updates = data.notifications.filter((n) => !(n.requires_acknowledgement && !n.acknowledged_at)).slice(0, 6);
  const first = data.employee.name.split(' ')[0];

  return (
    <div className="min-h-screen bg-[#F6F8FA]">
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 h-14 flex items-center gap-3">
          <span className="w-7 h-7 rounded bg-[#0E1B2C] text-white grid place-items-center text-xs font-bold">RQ</span>
          <div className="min-w-0">
            <p className="text-sm font-semibold truncate">{data.employee.name}</p>
            <p className="text-[11px] text-slate-500 truncate">{data.employee.role}{data.employee.department ? `, ${data.employee.department}` : ''} · {workspace.organization.name}</p>
          </div>
          <div className="flex-1" />
          <DemoSwitcher user={user} domain={workspace.domain} org={workspace.org} onSwitched={onSwitched} />
          <Button variant="ghost" aria-label={view === 'profile' ? 'Back to my dashboard' : 'My profile'} onClick={() => setView(view === 'profile' ? 'home' : 'profile')}>
            {view === 'profile' ? 'Dashboard' : <Avatar name={data.employee.name} src={user.avatar} size={24} />}</Button>
          <Button variant="ghost" icon={<LogOut className="w-3.5 h-3.5" />} onClick={onLogout}><span className="max-sm:sr-only">Sign out</span></Button>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 sm:px-6 py-6 space-y-6">
        {view === 'profile' ? <Profile onLogout={onLogout} /> : <>
        <EmployeeActions employeeId={user.employee_id ?? ''} onChanged={() => { reload(); rec.reload(); }} />
        {/* The three answers, at a glance */}
        <section aria-label="At a glance" className="grid md:grid-cols-3 gap-3">
          <Glance title="Next up" tone="neutral">
            {next ? <><b>{fmtDay(next.date)}, {next.start}–{next.end}</b><br />{next.assignment}</> : 'No upcoming work'}
          </Glance>
          <Glance title="Action needed" tone={toAck.length ? 'alert' : 'ok'}>
            {toAck.length ? <b>{toAck.length} schedule change{toAck.length > 1 ? 's' : ''} to acknowledge</b> : 'Nothing to do right now'}
          </Glance>
          <Glance title="Your requests" tone={openReqs.length ? 'info' : 'neutral'}>
            {openReqs.length ? <>{openReqs.length} in progress<br /><span className="text-slate-500">{openReqs.map((r) => `${fmtDay(r.date)}: ${r.status.replace('_', ' ')}`).slice(0, 2).join(' · ')}</span></> : 'No open requests'}
          </Glance>
        </section>

        <div className="grid lg:grid-cols-[1.55fr_1fr] gap-6 [&>*]:min-w-0">
          <div className="space-y-6">
            {toAck.length > 0 && (
              <section aria-label="Changes to acknowledge" className="rounded-lg border-2 border-[var(--accent)] bg-white">
                <div className="px-4 py-3 border-b border-slate-100 flex items-center gap-2">
                  <Bell className="w-4 h-4 text-[var(--accent)]" /><h2 className="text-sm font-semibold">What changed for you</h2>
                </div>
                <ul className="divide-y divide-slate-100">
                  {toAck.map((n) => (
                    <li key={n.id} className="p-4 space-y-2">
                      <p className="text-sm font-medium">{n.title}</p>
                      {(n.changes ?? []).map((c, i) => (
                        <div key={i} className="flex items-center gap-2 flex-wrap text-xs">
                          <span className="text-slate-500">{fmtDay(c.date)}</span>
                          {c.from_assignment && <span className="px-2 py-0.5 rounded bg-slate-100 text-slate-500 line-through">{c.from_assignment}{c.from_shift ? ` ${c.from_shift}` : ''}</span>}
                          {c.from_assignment && c.to_assignment && <ArrowRight className="w-3 h-3 text-slate-400" />}
                          {c.to_assignment && <span className="px-2 py-0.5 rounded bg-emerald-50 text-emerald-800 border border-emerald-200 font-medium">{c.to_assignment}{c.to_shift ? ` ${c.to_shift}` : ''}</span>}
                          {!c.to_assignment && <span className="text-slate-600">removed from your schedule</span>}
                        </div>
                      ))}
                      <p className="text-xs text-slate-600 whitespace-pre-line">{n.body.split('\n').filter((l) => l && !l.startsWith('•') && !l.startsWith('Hi ')).slice(0, 2).join(' ')}</p>
                      <div className="flex gap-2">
                        <Button size="sm" variant="primary" icon={<CheckCircle2 className="w-3.5 h-3.5" />}
                                onClick={async () => { await api.acknowledge(n.id); toast('Acknowledged. Your admin can see it.'); reload(); rec.reload(); }}>Acknowledge</Button>
                        {canSpeak() && <Button size="sm" icon={<Volume2 className="w-3.5 h-3.5" />} onClick={() => speak(n.voice_text ?? n.body)}>Read aloud</Button>}
                        <Button size="sm" variant="ghost" onClick={() => setFormOpen(true)}>This doesn't work for me</Button>
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {imOut.length > 0 && (
              <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900 flex gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                You're marked unavailable for {imOut.map((s) => `${s.assignment} on ${fmtDay(s.date)}`).join(', ')}. Your admin is arranging cover, so you don't need to do anything.
              </p>
            )}

            <Card>
              <CardHeader title={<span className="flex items-center gap-1.5"><CalendarDays className="w-4 h-4 text-slate-400" />My {t('shifts', 'shifts').toLowerCase()}</span>}
                          subtitle={`${data.employee.contracted_weekly_hours}h contracted per week`} />
              {byDay.length === 0 ? <EmptyState title="No upcoming work" /> : (
                <div className="divide-y divide-slate-100">
                  {byDay.map(([day, rows]) => (
                    <div key={day} className={`px-4 py-3 grid grid-cols-[5.5rem_minmax(0,1fr)] gap-3 ${day === today ? 'bg-[color-mix(in_srgb,var(--accent)_6%,white)]' : ''}`}>
                      <div className="text-xs">
                        <p className="font-semibold text-slate-800">{fmtDay(day)}</p>
                        {day === today && <p className="text-[11px] text-[var(--accent)] font-medium">Today</p>}
                      </div>
                      <ul className="space-y-1.5">
                        {rows.map((s) => (
                          <li key={s.shift_id} className="flex items-center gap-3 text-sm">
                            <span className="tabular-nums text-slate-600 w-[5.5rem] shrink-0 text-xs sm:text-sm">{s.start}–{s.end}</span>
                            <span className={`flex-1 min-w-0 truncate ${s.status === 'disrupted' ? 'line-through text-slate-400' : 'text-slate-900'}`}>{s.assignment}</span>
                            {s.status === 'changed' && (
                              <Why text={s.original_employee_name ? `Added to your schedule to cover for a colleague (previously ${s.original_employee_name}). Check the change above.` : 'Added to your schedule by an approved repair.'}>
                                <span className="text-[11px] px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-800">New</span></Why>)}
                            {s.status === 'disrupted' && <span className="text-[11px] text-amber-700">Being covered</span>}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            <Card>
              <CardHeader title="Updates" subtitle="Decisions on your requests, recognition and past changes" />
              {updates.length === 0 ? <CardBody className="p-4 text-xs text-slate-500">No updates yet.</CardBody> : (
                <ul className="divide-y divide-slate-100 text-xs">
                  {updates.map((n) => (
                    <li key={n.id} className="px-4 py-2.5 flex gap-2">
                      {n.kind === 'recognition' ? <AwardIcon className="w-3.5 h-3.5 text-[var(--accent)] mt-0.5 shrink-0" /> : <Bell className="w-3.5 h-3.5 text-slate-400 mt-0.5 shrink-0" />}
                      <span><b className="font-medium text-slate-800">{n.title}</b><br /><span className="text-slate-600">{n.kind === 'change' || !n.kind ? `Acknowledged ${n.acknowledged_at ? fmtWhen(n.acknowledged_at) : ''}` : n.body}</span></span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>

          <div className="space-y-6">
            <Card>
              <CardHeader title="My requests" subtitle="Your admin decides; you'll see the status here"
                          action={<Button size="sm" variant="primary" icon={<Plus className="w-3.5 h-3.5" />} onClick={() => setFormOpen(true)}>New request</Button>} />
              {data.requests.length === 0 ? <CardBody className="p-4 text-xs text-slate-500">You haven't made any requests.</CardBody> : (
                <ul className="divide-y divide-slate-100 text-xs">
                  {data.requests.map((r) => (
                    <li key={r.id} className="px-4 py-3">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium text-slate-900">{REQUEST_KIND[r.kind] ?? r.kind}, {fmtDay(r.date)}{r.start ? ` ${r.start}–${r.end}` : ''}</span>
                        <StatusPill status={r.status} />
                      </div>
                      {r.manager_note && <p className="text-slate-600 mt-1">Admin: {r.manager_note}</p>}
                      <ol className="mt-1.5 flex flex-wrap gap-x-2 text-[11px] text-slate-400" aria-label="Request history">
                        {(r.history ?? []).map((h, i) => <li key={i}>{h.status.replace('_', ' ')} {fmtWhen(h.at)}</li>)}
                      </ol>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <EmployeeRewardsCard employeeId={user.employee_id ?? ''} />
            <WorkloadCard employeeId={user.employee_id ?? ''} />
            <RecognitionCard data={rec.data} first={first} label={config?.label} />
          </div>
        </div>
      </>}
      </main>
      <RequestModal open={formOpen} onClose={() => setFormOpen(false)} employeeId={user.employee_id} today={today}
                    onDone={() => { setFormOpen(false); reload(); rec.reload(); }} />
    </div>
  );
}

function Glance({ title, tone, children }: { title: string; tone: 'ok' | 'alert' | 'info' | 'neutral'; children: React.ReactNode }) {
  const bar = { ok: 'bg-emerald-500', alert: 'bg-rose-500', info: 'bg-sky-500', neutral: 'bg-slate-300' }[tone];
  return (
    <div className="bg-white rounded-lg border border-slate-200 p-4 flex gap-3">
      <span className={`w-1 rounded-full ${bar}`} aria-hidden />
      <div className="text-sm text-slate-800"><p className="text-xs text-slate-500 mb-0.5">{title}</p>{children}</div>
    </div>
  );
}

function RecognitionCard({ data, first, label }: { data?: RecognitionSummary & { config: RecognitionConfig }; first: string; label?: string }) {
  if (!data) return <Card><Spinner /></Card>;
  const nextAt = data.next_tier?.points;
  const prevAt = data.tier?.points ?? 0;
  const pct = nextAt ? Math.min(100, (100 * (data.points_90d - prevAt)) / (nextAt - prevAt)) : 100;
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-1.5"><AwardIcon className="w-4 h-4 text-[var(--accent)]" />Recognition</span>}
                  subtitle={`${label ?? ''} recognition for helping the team`} />
      <CardBody className="p-4 space-y-3 text-xs">
        <div className="flex items-baseline justify-between">
          <span className="text-sm"><b>{data.tier?.label ?? 'Getting started'}</b></span>
          <span className="tabular-nums text-slate-600">{data.points_90d} points (90 days)</span>
        </div>
        <div className="h-1.5 rounded bg-slate-100 overflow-hidden" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}
             aria-label={data.next_tier ? `Progress to ${data.next_tier.label}` : 'Top level reached'}>
          <div className="h-full bg-[var(--accent)]" style={{ width: `${pct}%` }} />
        </div>
        <p className="text-slate-600">{data.next_tier ? `${data.next_tier.points - data.points_90d} more to ${data.next_tier.label}: ${data.next_tier.benefit}.` : data.tier ? `Benefit: ${data.tier.benefit}.` : ''}
          {data.tier && data.next_tier ? ` Current benefit: ${data.tier.benefit}.` : ''}</p>
        {data.categories.length > 0 ? (
          <ul className="space-y-1">
            {data.categories.map((c) => <li key={c.category} className="flex justify-between"><span>{c.label}</span><span className="text-slate-500 tabular-nums">×{c.count} · {c.points} pts</span></li>)}
          </ul>
        ) : <p className="text-slate-500">Cover for a colleague, acknowledge changes promptly or give early notice of absences to be recognized, {first}.</p>}
        {data.awards.slice(0, 3).map((a) => (
          <p key={a.id} className="text-slate-500 border-t border-slate-100 pt-2"><b className="text-slate-700 font-medium">{a.category_label}</b>: {a.reason} <span className="whitespace-nowrap">(+{a.points}, {a.awarded_by})</span></p>
        ))}
      </CardBody>
    </Card>
  );
}

function RequestModal({ open, onClose, employeeId, today, onDone }: {
  open: boolean; onClose: () => void; employeeId: string; today?: string; onDone: () => void;
}) {
  const toast = useToast();
  const [form, setForm] = useState<{ kind: RequestKind; date: string; start: string; end: string; reason: string }>({ kind: 'unavailable', date: '', start: '', end: '', reason: '' });
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if ((form.start && !form.end) || (!form.start && form.end)) { toast('Give both a start and an end time, or leave both empty for the whole day.', 'warning'); return; }
    setBusy(true);
    try {
      await api.submitAvailability(employeeId, { date: form.date, start: form.start || undefined, end: form.end || undefined, reason: form.reason, kind: form.kind });
      toast('Request sent. Your admin will see it right away.');
      setForm({ kind: 'unavailable', date: '', start: '', end: '', reason: '' });
      onDone();
    } catch (err) { toast(errorMessage(err), 'error'); } finally { setBusy(false); }
  }
  return (
    <Modal isOpen={open} onClose={onClose} title="New request" subtitle="Nothing changes until your admin approves it.">
      <form onSubmit={submit} className="space-y-3 text-xs">
        <label className="block text-slate-600">Type
          <select className="input w-full mt-1" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value as RequestKind })}>
            {Object.entries(REQUEST_KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label className="block text-slate-600">Date<input required type="date" min={today} className="input w-full mt-1" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} /></label>
        <div className="grid grid-cols-2 gap-2">
          <label className="block text-slate-600">From (optional, 24-hour)<div className="mt-1"><TimeInput value={form.start} onChange={(v) => setForm({ ...form, start: v })} /></div></label>
          <label className="block text-slate-600">To (optional, 24-hour)<div className="mt-1"><TimeInput value={form.end} onChange={(v) => setForm({ ...form, end: v })} /></div></label>
        </div>
        <label className="block text-slate-600">Note for your admin (private)<input className="input w-full mt-1" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></label>
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" disabled={busy}>{busy ? 'Sending…' : 'Send request'}</Button>
        </div>
      </form>
    </Modal>
  );
}
