// Requests: employee requests (existing screen) + admin requests to an employee, department, role, several
// people or eligible people. Every response syncs to both dashboards.
import { useMemo, useState } from 'react';
import { api, errorMessage } from '../api/client';
import type { AdminRequestType } from '../api/types';
import { Button } from '../components/common/Button';
import { Card, CardBody, CardHeader } from '../components/common/Card';
import { EmptyState, ErrorState, Spinner, useAsync, usePoll } from '../components/common/States';
import { Tabs } from '../components/common/Tabs';
import { Chip, Field, PageHeader, SeverityPill, TimeInput } from '../components/common/ui';
import { Send } from '../components/common/icons';
import { fmtWhen, isHHMM, titleCase } from '../lib/format';
import { useToast } from '../lib/toast';
import { Requests } from './Requests';

const TYPES: AdminRequestType[] = ['general', 'task', 'shift_coverage', 'availability_confirmation', 'schedule_confirmation', 'training',
  'emergency_coverage', 'volunteer_opportunity'];
type Target = 'employee' | 'employees' | 'department' | 'role' | 'eligible';

export function RequestsHub({ refreshKey, onChanged, onRepair }: { refreshKey: number; onChanged: () => void; onRepair: () => void }) {
  const [tab, setTab] = useState<'employee' | 'admin'>('employee');
  return (
    <div className="space-y-4">
      <Tabs items={[{ id: 'employee', label: 'Employee requests' }, { id: 'admin', label: 'Admin requests' }]} activeId={tab}
            onChange={(t) => setTab(t as 'employee' | 'admin')} variant="underline" />
      {tab === 'employee' ? <Requests refreshKey={refreshKey} onChanged={onChanged} onRepair={onRepair} /> : <AdminRequests refreshKey={refreshKey} />}
    </div>
  );
}

function AdminRequests({ refreshKey }: { refreshKey: number }) {
  const toast = useToast();
  const list = useAsync(() => api.adminRequests(), [refreshKey]);
  usePoll(list.reload, 10000);
  const emps = useAsync(() => api.employees(), [refreshKey]);
  const [f, setF] = useState({ type: 'general' as AdminRequestType, title: '', message: '', target: 'department' as Target, value: '', picked: [] as string[],
    severity: 0, date: '', start: '', end: '', skills: '' });
  const [busy, setBusy] = useState(false);
  const depts = useMemo(() => Array.from(new Set((emps.data ?? []).map((e) => e.department).filter((d): d is string => !!d))).sort(), [emps.data]);
  const roles = useMemo(() => Array.from(new Set((emps.data ?? []).map((e) => e.role))).sort(), [emps.data]);

  async function send() {
    const value = f.target === 'employees' ? f.picked : f.target === 'eligible'
      ? { date: f.date, start: f.start, end: f.end, skills: f.skills.split(',').map((s) => s.trim()).filter(Boolean) } : f.value;
    setBusy(true);
    try {
      const r = await api.createAdminRequest({ type: f.type, title: f.title, message: f.message, target: { kind: f.target, value }, severity: f.severity || undefined });
      toast(`Sent to ${r.recipients?.length ?? 0} employee(s).`);
      setF({ ...f, title: '', message: '' }); list.reload();
    } catch (e) { toast(errorMessage(e), 'error'); } finally { setBusy(false); }
  }
  const ready = f.title.trim() && (f.target === 'employees' ? f.picked.length > 0 : f.target === 'eligible' ? /^\d{4}-\d{2}-\d{2}$/.test(f.date) && isHHMM(f.start) && isHHMM(f.end) : f.value);

  return (
    <div className="space-y-4">
      <PageHeader title="Admin requests" subtitle="Ask people to confirm, accept or acknowledge something. Responses appear here instantly." />
      <Card>
        <CardHeader title="New request" />
        <CardBody className="p-4 grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <Field label="Type"><select className="input w-full" value={f.type} onChange={(e) => setF({ ...f, type: e.target.value as AdminRequestType })}>{TYPES.map((t) => <option key={t} value={t}>{titleCase(t)}</option>)}</select></Field>
          <Field label="Title" className="lg:col-span-2"><input className="input w-full" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
          <Field label="Level"><select className="input w-full" value={f.severity} onChange={(e) => setF({ ...f, severity: Number(e.target.value) })}>
            <option value={0}>Default for type</option><option value={1}>1 · Informational</option><option value={2}>2 · Important</option><option value={3}>3 · Critical</option></select></Field>
          <Field label="Message" className="sm:col-span-2 lg:col-span-4"><textarea className="input w-full h-16 py-1" value={f.message} onChange={(e) => setF({ ...f, message: e.target.value })} /></Field>
          <Field label="Send to"><select className="input w-full" value={f.target} onChange={(e) => setF({ ...f, target: e.target.value as Target, value: '' })}>
            <option value="employee">One employee</option><option value="employees">Several employees</option><option value="department">Department</option><option value="role">Role</option><option value="eligible">Eligible employees for a shift</option></select></Field>
          {f.target === 'employee' && <Field label="Employee"><select className="input w-full" value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })}><option value="">Choose…</option>{(emps.data ?? []).map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</select></Field>}
          {f.target === 'department' && <Field label="Department"><select className="input w-full" value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })}><option value="">Choose…</option>{depts.map((d) => <option key={d}>{d}</option>)}</select></Field>}
          {f.target === 'role' && <Field label="Role"><select className="input w-full" value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })}><option value="">Choose…</option>{roles.map((d) => <option key={d}>{d}</option>)}</select></Field>}
          {f.target === 'employees' && <Field label="Employees" className="sm:col-span-2 lg:col-span-3"><div className="max-h-32 overflow-y-auto border border-slate-200 rounded p-2 grid sm:grid-cols-2 gap-1">{(emps.data ?? []).map((e) => (
            <label key={e.id} className="flex items-center gap-1.5"><input type="checkbox" checked={f.picked.includes(e.id)}
              onChange={(x) => setF({ ...f, picked: x.target.checked ? [...f.picked, e.id] : f.picked.filter((i) => i !== e.id) })} />{e.name} <span className="text-slate-400">{e.role}</span></label>))}</div></Field>}
          {f.target === 'eligible' && <>
            <Field label="Date"><input className="input w-full font-mono" placeholder="YYYY-MM-DD" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></Field>
            <Field label="Start"><TimeInput value={f.start} onChange={(v) => setF({ ...f, start: v })} /></Field>
            <Field label="End"><TimeInput value={f.end} onChange={(v) => setF({ ...f, end: v })} /></Field>
            <Field label="Required skills"><input className="input w-full" value={f.skills} onChange={(e) => setF({ ...f, skills: e.target.value })} /></Field>
          </>}
          <div className="sm:col-span-2 lg:col-span-4"><Button variant="action" icon={<Send className="w-3.5 h-3.5" />} disabled={!ready || busy} onClick={send}>Send request</Button></div>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Sent requests" />
        {list.loading && !list.data ? <Spinner /> : list.error ? <ErrorState message={list.error} onRetry={list.reload} /> : !list.data?.length ? <EmptyState title="No admin requests yet" /> : (
          <ul className="divide-y divide-slate-100">{list.data.map((r) => {
            const rc = r.recipients ?? [];
            const count = (s: string) => rc.filter((x) => x.status === s).length;
            return (
              <li key={r.id} className="p-3 text-xs space-y-1.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="flex flex-wrap items-center gap-1.5"><SeverityPill level={r.severity} /><Chip>{titleCase(r.type)}</Chip><b>{r.title}</b><span className="text-slate-500">{fmtWhen(r.created_at)}</span></span>
                  <span className="flex items-center gap-2">
                    <span>{count('accepted')} accepted · {count('declined')} declined · {count('acknowledged')} acknowledged · {count('pending')} pending</span>
                    {r.status !== 'closed' && <Button size="sm" variant="ghost" onClick={() => api.closeAdminRequest(r.id).then(list.reload).catch((e) => toast(errorMessage(e), 'error'))}>Close</Button>}
                  </span>
                </div>
                <div className="flex flex-wrap gap-1">{rc.map((x) => <Chip key={x.employee_id} tone={x.status === 'accepted' || x.status === 'acknowledged' ? 'green' : x.status === 'declined' ? 'red' : 'slate'}>{x.employee_name}: {x.status}{x.note ? ` (“${x.note}”)` : ''}</Chip>)}</div>
              </li>);
          })}</ul>
        )}
      </Card>
    </div>
  );
}
