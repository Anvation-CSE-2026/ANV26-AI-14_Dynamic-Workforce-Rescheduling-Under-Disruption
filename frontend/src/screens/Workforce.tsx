// Workforce augmentation: staffing gaps → find eligible employees → request additional workforce →
// assign directly, invite volunteers, broadcast or escalate → approve volunteers → mark completed.
import { useEffect, useState } from 'react';
import { api, errorMessage } from '../api/client';
import type { Candidate, CandidateSearch, StaffingGap, WorkforceForm, WorkforceRequest } from '../api/types';
import { Button } from '../components/common/Button';
import { Card, CardBody, CardHeader } from '../components/common/Card';
import { EmptyState, ErrorState, Spinner, useAsync, usePoll } from '../components/common/States';
import { CheckRow, Chip, Field, MiniBar, Notice, PageHeader, TimeInput } from '../components/common/ui';
import { CheckCircle2, Megaphone, Search, UserPlus, Users, Zap } from '../components/common/icons';
import { fmtDay, fmtRange, fmtWhen, isHHMM } from '../lib/format';
import { useToast } from '../lib/toast';

const blank = (date = ''): WorkforceForm => ({ task: '', date, start: '07:00', end: '15:00', additional_needed: 1, skills: [],
  certifications: [], priority: 'normal', reason: '' });

export function Workforce({ refreshKey, prefill, onChanged }: { refreshKey: number; prefill?: StaffingGap | null; onChanged: () => void }) {
  const toast = useToast();
  const gaps = useAsync(() => api.staffingGaps(), [refreshKey]);
  const reqs = useAsync(() => api.workforceRequests(), [refreshKey]);
  usePoll(reqs.reload, 10000);
  const [form, setForm] = useState<WorkforceForm>(blank());
  const [skills, setSkills] = useState('');
  const [certs, setCerts] = useState('');
  const [found, setFound] = useState<CandidateSearch | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const fromGap = (g: StaffingGap) => {
    setForm({ task: g.task, date: g.date, start: g.start, end: g.end, required_employees: g.required, additional_needed: g.gap,
      department: g.department ?? undefined, location: g.location ?? undefined, skills: g.skills, certifications: g.certifications,
      priority: g.priority, reason: `Staffing gap: ${g.assigned} of ${g.required} assigned`, gap_id: g.id });
    setSkills(g.skills.join(', '));
    setCerts(g.certifications.join(', '));
    setFound(null);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };
  useEffect(() => { if (prefill) fromGap(prefill); }, [prefill]);

  const payload = (): WorkforceForm => ({ ...form, skills: split(skills), certifications: split(certs) });
  const valid = form.task.trim() && /^\d{4}-\d{2}-\d{2}$/.test(form.date) && isHHMM(form.start) && isHHMM(form.end) && form.additional_needed >= 1;

  async function find() {
    setBusy('find');
    try { setFound(await api.findEmployees(payload())); } catch (e) { toast(errorMessage(e), 'error'); } finally { setBusy(null); }
  }
  async function create() {
    setBusy('create');
    try {
      const w = await api.createWorkforceRequest(payload());
      toast(w.sufficient ? `Workforce request created: ${w.eligible_count} eligible.` : (w.message ?? 'Created.'), w.sufficient ? 'success' : 'warning');
      setOpen(w.id); setFound(null); setForm(blank(form.date)); setSkills(''); setCerts('');
      reqs.reload(); onChanged();
    } catch (e) { toast(errorMessage(e), 'error'); } finally { setBusy(null); }
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Workforce requests" subtitle="Detect staffing gaps, find eligible people (hard constraints first, then fairness), and request additional workforce or volunteers. Volunteering never assigns anyone until you approve." />
      <Card>
        <CardHeader title="Staffing gaps" subtitle="Tasks where fewer people can work than the task requires" />
        {gaps.loading && !gaps.data ? <Spinner /> : gaps.error ? <ErrorState message={gaps.error} onRetry={gaps.reload} /> :
          !gaps.data?.length ? <EmptyState title="No staffing gaps" /> : (
            <ul className="divide-y divide-slate-100">
              {gaps.data.map((g) => (
                <li key={g.id} className="p-3 flex flex-wrap items-center justify-between gap-2 text-xs">
                  <span><Chip tone={g.priority === 'critical' ? 'red' : g.priority === 'high' ? 'amber' : 'slate'}>{g.priority}</Chip>{' '}
                    <b>{g.task}</b> · {fmtDay(g.date)} {fmtRange(g.start, g.end)} · <b className="text-rose-700">{g.gap} more needed</b> ({g.assigned}/{g.required} assigned){g.skills.length ? ` · ${g.skills.join(', ')}` : ''}</span>
                  <Button size="sm" variant="action" icon={<Search className="w-3.5 h-3.5" />} onClick={() => fromGap(g)}>Find employees</Button>
                </li>
              ))}
            </ul>
          )}
      </Card>

      <Card>
        <CardHeader title="Request additional workforce" subtitle="24-hour times (e.g. 07:00, 19:00)" />
        <CardBody className="p-4 grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <Field label="Task / project" className="sm:col-span-2"><input className="input w-full" value={form.task} onChange={(e) => setForm({ ...form, task: e.target.value })} /></Field>
          <Field label="Date"><input className="input w-full font-mono" placeholder="YYYY-MM-DD" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} /></Field>
          <Field label="Priority">
            <select className="input w-full" value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value as WorkforceForm['priority'] })}>
              <option value="normal">Normal</option><option value="high">High</option><option value="critical">Critical</option>
            </select>
          </Field>
          <Field label="Start"><TimeInput value={form.start} onChange={(v) => setForm({ ...form, start: v })} /></Field>
          <Field label="End"><TimeInput value={form.end} onChange={(v) => setForm({ ...form, end: v })} /></Field>
          <Field label="Required employees"><input type="number" min={1} className="input w-full" value={form.required_employees ?? ''} onChange={(e) => setForm({ ...form, required_employees: Number(e.target.value) || undefined })} /></Field>
          <Field label="Additional needed"><input type="number" min={1} max={50} className="input w-full" value={form.additional_needed} onChange={(e) => setForm({ ...form, additional_needed: Number(e.target.value) || 1 })} /></Field>
          <Field label="Required skills" hint="comma-separated"><input className="input w-full" value={skills} onChange={(e) => setSkills(e.target.value)} /></Field>
          <Field label="Certifications" hint="comma-separated"><input className="input w-full" value={certs} onChange={(e) => setCerts(e.target.value)} /></Field>
          <Field label="Department"><input className="input w-full" value={form.department ?? ''} onChange={(e) => setForm({ ...form, department: e.target.value })} /></Field>
          <Field label="Location"><input className="input w-full" value={form.location ?? ''} onChange={(e) => setForm({ ...form, location: e.target.value })} /></Field>
          <Field label="Reason" className="sm:col-span-2 lg:col-span-3"><input className="input w-full" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></Field>
          <label className="flex items-center gap-2 text-xs text-slate-700 self-end"><input type="checkbox" checked={!!form.emergency} onChange={(e) => setForm({ ...form, emergency: e.target.checked })} /> Emergency coverage</label>
          <div className="sm:col-span-2 lg:col-span-4 flex flex-wrap gap-2">
            <Button icon={<Search className="w-3.5 h-3.5" />} disabled={!valid || busy === 'find'} onClick={find}>{busy === 'find' ? 'Searching…' : 'Find employees'}</Button>
            <Button variant="action" icon={<UserPlus className="w-3.5 h-3.5" />} disabled={!valid || busy === 'create'} onClick={create}>Create workforce request</Button>
          </div>
        </CardBody>
        {found && <CardBody className="p-4 border-t border-slate-100"><Candidates s={found} /></CardBody>}
      </Card>

      <Card>
        <CardHeader title="Requests" subtitle="Open, filled and cancelled requests with volunteers and assignments" />
        {reqs.loading && !reqs.data ? <Spinner /> : reqs.error ? <ErrorState message={reqs.error} onRetry={reqs.reload} /> :
          !reqs.data?.length ? <EmptyState title="No workforce requests yet" /> : (
            <ul className="divide-y divide-slate-100">
              {reqs.data.map((w) => <RequestRow key={w.id} w={w} open={open === w.id} onToggle={() => setOpen(open === w.id ? null : w.id)}
                                                onChanged={() => { reqs.reload(); gaps.reload(); onChanged(); }} />)}
            </ul>
          )}
      </Card>
    </div>
  );
}

const split = (v: string) => v.split(',').map((x) => x.trim()).filter(Boolean);

function Candidates({ s, onAssign, assigned = [] }: { s: CandidateSearch; onAssign?: (c: Candidate) => void; assigned?: string[] }) {
  const max = Math.max(1, ...s.eligible.map((c) => c.fairness.contribution_load));
  return (
    <div className="space-y-3 text-xs">
      <p className="text-slate-600">Pipeline: {s.funnel.map((f) => `${f.stage} ${f.remaining}`).join(' → ')}</p>
      {!s.sufficient && <Notice tone="warning"><b>{s.message}</b> Request volunteers, escalate, or create the workforce request so more people can be invited.</Notice>}
      {s.eligible.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead className="text-[11px] text-slate-500 uppercase"><tr><th className="py-1 pr-2">Rank</th><th className="pr-2">Employee</th><th className="pr-2">Hours this week</th><th className="pr-2">Recent extra work</th><th className="pr-2">Notes</th><th /></tr></thead>
            <tbody>
              {s.eligible.slice(0, 12).map((c) => (
                <tr key={c.employee_id} className="border-t border-slate-100">
                  <td className="py-1.5 pr-2 font-mono">#{c.rank}</td>
                  <td className="pr-2"><b>{c.employee_name}</b><span className="text-slate-500"> · {c.role}</span></td>
                  <td className="pr-2">{c.weekly_hours_before} → {c.weekly_hours_after} h</td>
                  <td className="pr-2"><MiniBar value={c.fairness.contribution_load} max={max} /> {c.fairness.contribution_load} <span className="text-slate-400">({c.fairness.volunteer_assignments} volunteer)</span></td>
                  <td className="pr-2">{c.soft?.filter((n) => n.status === 'warn').map((n) => n.detail).join(', ') || 'all soft checks good'}</td>
                  <td className="text-right">{onAssign && !assigned.includes(c.employee_id) && <Button size="sm" onClick={() => onAssign(c)}>Assign</Button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {s.ineligible.length > 0 && (
        <details><summary className="cursor-pointer text-slate-600">{s.ineligible.length} not eligible (hard constraints)</summary>
          <ul className="mt-1 grid sm:grid-cols-2 gap-x-4">{s.ineligible.slice(0, 30).map((c) => <CheckRow key={c.employee_id} ok={false} label={c.employee_name} detail={c.failed ? `${c.failed.name}: ${c.failed.detail}` : ''} />)}</ul>
        </details>
      )}
    </div>
  );
}

function RequestRow({ w, open, onToggle, onChanged }: { w: WorkforceRequest; open: boolean; onToggle: () => void; onChanged: () => void }) {
  const toast = useToast();
  const [full, setFull] = useState<WorkforceRequest | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) api.workforceRequest(w.id).then(setFull).catch((e) => toast(errorMessage(e), 'error')); }, [open, w.updated_at]);
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    try { await fn(); toast(ok); onChanged(); setFull(await api.workforceRequest(w.id)); } catch (e) { toast(errorMessage(e), 'error'); } finally { setBusy(false); }
  };
  const tone = w.status === 'filled' ? 'green' : w.status === 'cancelled' ? 'slate' : w.status === 'partially_filled' ? 'blue' : 'amber';
  const active = w.status === 'open' || w.status === 'partially_filled';
  return (
    <li className="p-3 text-xs space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button className="text-left" onClick={onToggle} aria-expanded={open}>
          <Chip tone={tone}>{w.status.replace('_', ' ')}</Chip> {w.emergency && <Chip tone="red">emergency</Chip>}{' '}
          <b>{w.task}</b> · {fmtDay(w.date)} {fmtRange(w.start, w.end)} · {w.assignments.length}/{w.additional_needed} filled · {w.volunteers.filter((v) => v.status === 'volunteered').length} volunteer(s) waiting · {w.invited.length} invited
        </button>
        {active && (
          <div className="flex flex-wrap gap-1.5">
            <Button size="sm" icon={<Users className="w-3.5 h-3.5" />} disabled={busy} onClick={() => run(() => api.requestVolunteers(w.id, 'volunteers'), 'Volunteer opportunity sent to the top eligible employees.')}>Request volunteers</Button>
            <Button size="sm" icon={<Megaphone className="w-3.5 h-3.5" />} disabled={busy} onClick={() => run(() => api.requestVolunteers(w.id, 'broadcast'), 'Broadcast to every eligible employee.')}>Broadcast</Button>
            <Button size="sm" variant="destructive" icon={<Zap className="w-3.5 h-3.5" />} disabled={busy} onClick={() => run(() => api.requestVolunteers(w.id, 'escalate'), 'Escalated: critical notification on all channels.')}>Escalate</Button>
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => run(() => api.cancelWorkforce(w.id), 'Request cancelled.')}>Cancel</Button>
          </div>
        )}
      </div>
      {open && !full && <Spinner />}
      {open && full && (
        <div className="grid lg:grid-cols-2 gap-3">
          <div className="space-y-2">
            {w.reason && <p className="text-slate-600">Reason: {w.reason}</p>}
            <p className="font-semibold text-slate-800">Volunteers</p>
            {!full.volunteers.length ? <p className="text-slate-500">No responses yet.</p> : (
              <ul className="space-y-1">{full.volunteers.map((v) => (
                <li key={v.employee_id} className="flex flex-wrap items-center justify-between gap-2">
                  <span><b>{v.employee_name}</b> · {v.status.replace('_', ' ')} · {v.eligible ? 'passes hard constraints' : v.validation}{v.rank ? ` · fairness rank #${v.rank}` : ''}</span>
                  {v.status === 'volunteered' && active && (
                    <span className="flex gap-1">
                      <Button size="sm" variant="action" disabled={busy || !v.eligible} onClick={() => run(() => api.decideVolunteer(w.id, v.employee_id, true), `${v.employee_name} assigned.`)}>Approve</Button>
                      <Button size="sm" variant="ghost" disabled={busy} onClick={() => run(() => api.decideVolunteer(w.id, v.employee_id, false), 'Volunteer thanked; not selected.')}>Not selected</Button>
                    </span>
                  )}
                </li>
              ))}</ul>
            )}
            <p className="font-semibold text-slate-800 pt-2">Assignments</p>
            {!full.assignments.length ? <p className="text-slate-500">Nobody assigned yet.</p> : (
              <ul className="space-y-1">{full.assignments.map((a) => (
                <li key={a.employee_id} className="flex flex-wrap items-center justify-between gap-2">
                  <span><b>{a.employee_name}</b> · {a.volunteer ? 'volunteer' : 'direct'} · {a.status}{a.completed_at ? ` ${fmtWhen(a.completed_at)}` : ''}</span>
                  {a.status === 'assigned' && <Button size="sm" icon={<CheckCircle2 className="w-3.5 h-3.5" />} disabled={busy} onClick={() => run(() => api.completeAssignment(w.id, a.employee_id), 'Completed. Reward eligibility triggered.')}>Mark completed</Button>}
                </li>
              ))}</ul>
            )}
          </div>
          <div>
            {full.candidates && <Candidates s={full.candidates} assigned={full.assignments.map((a) => a.employee_id)}
              onAssign={active ? (c) => run(() => api.assignWorkforce(w.id, c.employee_id), `${c.employee_name} assigned directly.`) : undefined} />}
          </div>
        </div>
      )}
    </li>
  );
}

