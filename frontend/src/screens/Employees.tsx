// Employee management: directory, add one, edit admin-controlled fields, deactivate/reactivate (never delete),
// reset password, and bulk import of employees and schedules (upload → validate → preview → confirm).
import { useMemo, useState } from 'react';
import { api, errorMessage } from '../api/client';
import type { DirectoryEmployee, ImportJob } from '../api/types';
import { Button } from '../components/common/Button';
import { Card, CardHeader } from '../components/common/Card';
import { Modal } from '../components/common/Modal';
import { EmptyState, ErrorState, Spinner, useAsync } from '../components/common/States';
import { Tabs } from '../components/common/Tabs';
import { Chip, Field, FileDrop, MiniBar, Notice, PageHeader, TimeInput } from '../components/common/ui';
import { Download, KeyRound, PenLine, Search, UserPlus } from '../components/common/icons';
import { useToast } from '../lib/toast';

type Tab = 'directory' | 'import_employees' | 'import_schedule';

export function Employees({ refreshKey, onChanged }: { refreshKey: number; onChanged: () => void }) {
  const [tab, setTab] = useState<Tab>('directory');
  return (
    <div className="space-y-4">
      <PageHeader title="Employees" subtitle="Add people without replacing anyone. Deactivate instead of deleting. Imports show every row before anything is created." />
      <Tabs<Tab> items={[{ id: 'directory', label: 'Directory' }, { id: 'import_employees', label: 'Import employees' }, { id: 'import_schedule', label: 'Import schedule' }]}
                 activeId={tab} onChange={setTab} variant="underline" />
      {tab === 'directory' && <Directory refreshKey={refreshKey} onChanged={onChanged} />}
      {tab === 'import_employees' && <ImportFlow kind="employees" onChanged={onChanged} />}
      {tab === 'import_schedule' && <ImportFlow kind="schedule" onChanged={onChanged} />}
    </div>
  );
}

function Directory({ refreshKey, onChanged }: { refreshKey: number; onChanged: () => void }) {
  const toast = useToast();
  const { data, loading, error, reload } = useAsync(() => api.directory(), [refreshKey]);
  const [q, setQ] = useState('');
  const [status, setStatus] = useState<'all' | 'active' | 'inactive'>('active');
  const [edit, setEdit] = useState<DirectoryEmployee | null>(null);
  const [adding, setAdding] = useState(false);
  const rows = useMemo(() => (data ?? []).filter((e) => (status === 'all' || (e.status ?? 'active') === status)
    && `${e.name} ${e.id} ${e.role} ${e.department ?? ''} ${e.skills.join(' ')}`.toLowerCase().includes(q.toLowerCase())), [data, q, status]);
  const maxLoad = Math.max(1, ...(data ?? []).map((e) => e.fairness.contribution_load));

  async function toggle(e: DirectoryEmployee) {
    const next = e.status === 'inactive' ? 'active' : 'inactive';
    if (next === 'inactive' && !window.confirm(`Deactivate ${e.name}? Their future shifts become disruptions to repair. Nothing is deleted.`)) return;
    try {
      const r = await api.setEmployeeStatus(e.id, next);
      toast(next === 'inactive' ? `${e.name} deactivated${r.disruptions.length ? `; ${r.disruptions.length} day(s) need cover` : ''}.` : `${e.name} reactivated.`);
      reload(); onChanged();
    } catch (err) { toast(errorMessage(err), 'error'); }
  }
  async function createLogins() {
    try {
      const r = await api.createEmployeeLogins();
      await api.downloadCredentials(r.credentials_token);
      toast(`${r.created} login(s) created. The password file downloads once; share each row privately.`);
      reload();
    } catch (err) { toast(errorMessage(err), 'error'); }
  }
  async function reset(e: DirectoryEmployee) {
    try { const r = await api.resetPassword(e.id); await api.downloadCredentials(r.credentials_token); toast('Temporary password downloaded (one time).'); }
    catch (err) { toast(errorMessage(err), 'error'); }
  }

  return (
    <Card>
      <div className="p-3 flex flex-wrap gap-2 items-center border-b border-slate-100">
        <div className="relative flex-1 min-w-[12rem]"><Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-slate-400" />
          <input aria-label="Search employees" className="input w-full pl-8" placeholder="Search name, ID, role, skill" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <select aria-label="Status" className="input" value={status} onChange={(e) => setStatus(e.target.value as typeof status)}>
          <option value="active">Active</option><option value="inactive">Inactive</option><option value="all">All</option>
        </select>
        <Button icon={<KeyRound className="w-3.5 h-3.5" />} onClick={createLogins}>Create employee logins</Button>
        <Button variant="action" icon={<UserPlus className="w-3.5 h-3.5" />} onClick={() => setAdding(true)}>Add employee</Button>
      </div>
      {data && data.some((e) => !e.login && e.status !== 'inactive') && (
        <div className="px-3 pt-3"><Notice tone="info">
          {data.filter((e) => !e.login && e.status !== 'inactive').length} employee(s) can't sign in yet. Click <b>Create employee logins</b> to
          download their sign-in IDs and one-time temporary passwords (.xlsx). Employees sign in from the home page and set their own password.
        </Notice></div>
      )}
      {loading && !data ? <Spinner /> : error ? <ErrorState message={error} onRetry={reload} /> : !rows.length ? <EmptyState title="No employees match" /> : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs text-left">
            <thead className="text-[11px] uppercase text-slate-500 bg-slate-50"><tr>
              <th className="px-3 py-2">Employee</th><th className="px-2">Department</th><th className="px-2">Skills</th><th className="px-2">Shifts</th><th className="px-2">Recent extra work</th><th className="px-2">Status</th><th className="px-2">Sign-in</th><th /></tr></thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.id} className="border-t border-slate-100">
                  <td className="px-3 py-2"><b className="text-slate-900">{e.name}</b><div className="text-slate-500">{e.id} · {e.role}</div></td>
                  <td className="px-2">{e.department ?? '—'}</td>
                  <td className="px-2 max-w-[16rem]">{[...e.skills, ...e.certifications].join(', ')}</td>
                  <td className="px-2">{e.shifts} · {e.fairness.weekly_hours} h/wk</td>
                  <td className="px-2 whitespace-nowrap"><MiniBar value={e.fairness.contribution_load} max={maxLoad} /> {e.fairness.contribution_load}</td>
                  <td className="px-2"><Chip tone={e.status === 'inactive' ? 'slate' : 'green'}>{e.status ?? 'active'}</Chip></td>
                  <td className="px-2">{e.login ? <span className="text-slate-600">{e.login}</span> : <Chip tone="amber">no login</Chip>}</td>
                  <td className="px-2 text-right whitespace-nowrap">
                    <Button size="sm" variant="ghost" aria-label={`Edit ${e.name}`} icon={<PenLine className="w-3.5 h-3.5" />} onClick={() => setEdit(e)}>Edit</Button>
                    <Button size="sm" variant="ghost" aria-label={`${e.login ? 'Reset password' : 'Create login'} for ${e.name}`} icon={<KeyRound className="w-3.5 h-3.5" />} onClick={() => reset(e)}>{e.login ? 'Reset' : 'Create login'}</Button>
                    <Button size="sm" variant={e.status === 'inactive' ? 'secondary' : 'destructive'} onClick={() => toggle(e)}>{e.status === 'inactive' ? 'Reactivate' : 'Deactivate'}</Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {edit && <EditModal e={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload(); onChanged(); }} />}
      {adding && <AddModal onClose={() => setAdding(false)} onSaved={() => { setAdding(false); reload(); onChanged(); }} />}
    </Card>
  );
}

function EditModal({ e, onClose, onSaved }: { e: DirectoryEmployee; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [f, setF] = useState({ name: e.name, email: e.email ?? '', phone: e.phone ?? '', department: e.department ?? '', role: e.role,
    skills: e.skills.join(', '), certifications: e.certifications.join(', '), contracted_weekly_hours: String(e.contracted_weekly_hours),
    max_weekly_hours: String(e.max_weekly_hours) });
  const [busy, setBusy] = useState(false);
  async function save() {
    setBusy(true);
    try {
      await api.updateEmployee(e.id, { name: f.name, email: f.email || null, phone: f.phone || null, department: f.department || null, role: f.role,
        skills: split(f.skills), certifications: split(f.certifications), contracted_weekly_hours: Number(f.contracted_weekly_hours),
        max_weekly_hours: Number(f.max_weekly_hours) });
      toast(`${f.name} updated.`); onSaved();
    } catch (err) { toast(errorMessage(err), 'error'); } finally { setBusy(false); }
  }
  const input = (k: keyof typeof f, label: string) => <Field label={label}><input className="input w-full" value={f[k]} onChange={(x) => setF({ ...f, [k]: x.target.value })} /></Field>;
  return (
    <Modal isOpen onClose={onClose} title={`Edit ${e.name}`} subtitle={`Employee ID ${e.id} (fixed)`} maxWidth="xl"
           footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" disabled={busy} onClick={save}>Save</Button></>}>
      <div className="grid sm:grid-cols-2 gap-3">
        {input('name', 'Name')}{input('role', 'Role / designation')}{input('email', 'Email')}{input('phone', 'Phone')}
        {input('department', 'Department')}{input('skills', 'Skills (comma-separated)')}{input('certifications', 'Certifications')}
        {input('contracted_weekly_hours', 'Contracted hours / week')}{input('max_weekly_hours', 'Maximum hours / week')}
      </div>
    </Modal>
  );
}

function AddModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [f, setF] = useState<Record<string, string>>({ employee_id: '', name: '', email: '', phone: '', department: '', role: '', skills: '',
    certifications: '', availability_start: '', availability_end: '', max_hours: '' });
  const [busy, setBusy] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  async function save() {
    setBusy(true);
    try { const r = await api.addEmployee(f); setToken(r.credentials_token); toast(`${f.name} added.`); }
    catch (err) { toast(errorMessage(err), 'error'); } finally { setBusy(false); }
  }
  const input = (k: string, label: string) => <Field label={label}><input className="input w-full" value={f[k]} onChange={(x) => setF({ ...f, [k]: x.target.value })} /></Field>;
  if (token) return (
    <Modal isOpen onClose={onSaved} title="Employee added" footer={<Button variant="primary" onClick={onSaved}>Done</Button>}>
      <Notice tone="warning">Download the temporary password now. It can be downloaded <b>once</b>; the employee must change it at first sign-in.</Notice>
      <div className="mt-3"><Button variant="action" icon={<Download className="w-3.5 h-3.5" />} onClick={() => api.downloadCredentials(token).then(() => toast('Downloaded.')).catch((e) => toast(errorMessage(e), 'error'))}>Download temporary password (.xlsx)</Button></div>
    </Modal>
  );
  return (
    <Modal isOpen onClose={onClose} title="Add employee" maxWidth="xl"
           footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" disabled={busy} onClick={save}>Add employee</Button></>}>
      <div className="grid sm:grid-cols-2 gap-3">
        {input('employee_id', 'Employee ID')}{input('name', 'Full name')}{input('email', 'Email')}{input('phone', 'Phone')}
        {input('department', 'Department')}{input('role', 'Role')}{input('skills', 'Skills (comma or ; separated)')}{input('certifications', 'Certifications')}
        <Field label="Available from (optional)"><TimeInput value={f.availability_start} onChange={(v) => setF({ ...f, availability_start: v })} /></Field>
        <Field label="Available until (optional)"><TimeInput value={f.availability_end} onChange={(v) => setF({ ...f, availability_end: v })} /></Field>
        {input('max_hours', 'Maximum hours / week (optional)')}
      </div>
    </Modal>
  );
}

const split = (v: string) => v.split(/[,;]/).map((x) => x.trim()).filter(Boolean);

function ImportFlow({ kind, onChanged }: { kind: 'employees' | 'schedule'; onChanged: () => void }) {
  const toast = useToast();
  const [job, setJob] = useState<ImportJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [warn, setWarn] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [filter, setFilter] = useState<'all' | 'valid' | 'invalid' | 'duplicate' | 'existing'>('all');
  async function preview(f: File) {
    setBusy(true); setJob(null); setToken(null);
    try { setJob(kind === 'employees' ? await api.previewEmployeeImport(f) : await api.previewScheduleImport(f)); }
    catch (e) { toast(errorMessage(e), 'error'); } finally { setBusy(false); }
  }
  async function confirm() {
    if (!job) return;
    setBusy(true);
    try {
      if (kind === 'employees') {
        const r = await api.confirmEmployeeImport(job.id);
        setToken(r.credentials_token);
        toast(`${r.created.length} employee(s) created, ${r.accounts} login(s).`);
      } else {
        const r = await api.confirmScheduleImport(job.id, warn);
        toast(`${r.imported} shift(s) imported into schedule ${r.version}; ${r.skipped} row(s) not imported.`);
        setJob(null);
      }
      onChanged();
    } catch (e) { toast(errorMessage(e), 'error'); } finally { setBusy(false); }
  }
  const r = job?.report;
  const rows = (r?.rows ?? []).filter((x) => filter === 'all' || x.status === filter);
  return (
    <div className="space-y-3">
      <Card>
        <CardHeader title={kind === 'employees' ? 'Bulk add employees (CSV or XLSX)' : 'Import schedule (CSV or XLSX)'}
                    subtitle={kind === 'employees' ? 'Required: employee_id, name, email, phone, department, role, skills. Existing employees are never replaced.'
                      : 'Required: schedule_id, employee_id, date, shift_start, shift_end, location, task, required_skill. 24-hour times.'}
                    action={<div className="flex gap-1.5">
                      <Button size="sm" icon={<Download className="w-3.5 h-3.5" />} onClick={() => api.downloadTemplate(`${kind}.csv`).catch((e) => toast(errorMessage(e), 'error'))}>CSV template</Button>
                      <Button size="sm" icon={<Download className="w-3.5 h-3.5" />} onClick={() => api.downloadTemplate(`${kind}.xlsx`).catch((e) => toast(errorMessage(e), 'error'))}>XLSX template</Button></div>} />
        <div className="p-4">{busy && !job ? <Spinner label="Validating…" /> : <FileDrop accept=".csv,.xlsx" onFile={preview} label="Choose a file" hint="CSV (UTF-8) or Excel .xlsx, up to 5 MB" />}</div>
      </Card>
      {token && (
        <Notice tone="warning">
          Temporary passwords are ready. Download them <b>now</b>: the file is available once, then it's gone. Employees must change the password at first sign-in.
          <div className="mt-2"><Button size="sm" variant="action" icon={<Download className="w-3.5 h-3.5" />} onClick={() => api.downloadCredentials(token).then(() => { toast('Downloaded.'); setToken(null); setJob(null); }).catch((e) => toast(errorMessage(e), 'error'))}>Download temporary passwords (.xlsx)</Button></div>
        </Notice>
      )}
      {r && !token && (
        <Card>
          <div className="p-3 flex flex-wrap items-center gap-2 border-b border-slate-100 text-xs">
            <b>{job?.filename}</b>
            {(['all', 'valid', 'invalid', 'duplicate', 'existing'] as const).map((k) => (
              <button key={k} onClick={() => setFilter(k)} aria-pressed={filter === k}
                      className={`px-2 py-0.5 rounded border ${filter === k ? 'bg-slate-900 text-white border-slate-900' : 'border-slate-200'}`}>
                {k} {k === 'all' ? r.total : k === 'valid' ? r.valid : k === 'invalid' ? r.invalid : k === 'duplicate' ? r.duplicates : r.existing}
              </button>
            ))}
            <span className="text-slate-500">{r.warnings} warning(s)</span>
            <span className="flex-1" />
            {kind === 'schedule' && <label className="flex items-center gap-1.5"><input type="checkbox" checked={warn} onChange={(e) => setWarn(e.target.checked)} />Import rows with hard-constraint warnings</label>}
            <Button variant="primary" disabled={busy || !r.valid} onClick={confirm}>{kind === 'employees' ? `Create ${r.valid} new employee(s)` : `Import ${r.valid} row(s)`}</Button>
          </div>
          <div className="overflow-x-auto max-h-[28rem]">
            <table className="w-full text-xs text-left">
              <thead className="text-[11px] uppercase text-slate-500 bg-slate-50 sticky top-0"><tr><th className="px-3 py-2">Row</th><th className="px-2">Status</th><th className="px-2">Record</th><th className="px-2">Errors / warnings</th></tr></thead>
              <tbody>{rows.map((x) => (
                <tr key={x.row} className="border-t border-slate-100 align-top">
                  <td className="px-3 py-1.5 font-mono">{x.row}</td>
                  <td className="px-2"><Chip tone={x.status === 'valid' ? (x.hard_warning ? 'amber' : 'green') : x.status === 'existing' ? 'blue' : 'red'}>{x.status}</Chip></td>
                  <td className="px-2">{Object.entries(x.data).filter(([, v]) => v !== null && v !== '' && !(Array.isArray(v) && !v.length)).slice(0, 6).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(';') : String(v)}`).join(' · ')}</td>
                  <td className="px-2"><ul>{x.errors.map((m) => <li key={m} className="text-rose-700">{m}</li>)}{x.warnings.map((m) => <li key={m} className="text-amber-700">{m}</li>)}</ul></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
