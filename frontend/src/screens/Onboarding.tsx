import React, { useEffect, useMemo, useState } from 'react';
import { CheckCircle2, AlertTriangle, XCircle, FileJson, FileSpreadsheet, PenLine, Sparkles, Plus, Trash2 } from '../components/common/icons';
import { api, errorMessage } from '../api/client';
import type { DomainId, DomainSummary, ValidationReport, WorkspaceSummary } from '../api/types';
import { Button } from '../components/common/Button';
import { Card, CardBody, CardHeader } from '../components/common/Card';
import { DomainIcon } from '../components/common/DomainIcon';
import { useToast } from '../lib/toast';

type Source = 'demo' | 'json' | 'csv' | 'manual';
type Step = 1 | 2 | 3 | 4;

export function Onboarding({ onDone, onCancel }: { onDone: (ws: WorkspaceSummary) => void; onCancel?: () => void }) {
  const toast = useToast();
  const [step, setStep] = useState<Step>(1);
  const [domains, setDomains] = useState<DomainSummary[]>([]);
  const [org, setOrg] = useState({ name: '', domain: 'healthcare' as DomainId, location: 'Bengaluru', size: '', timezone: 'Asia/Kolkata' });
  const [source, setSource] = useState<Source>('demo');
  const [raw, setRaw] = useState<RawDataset | null>(null);
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [csv, setCsv] = useState<{ schedule: File | null; employees: File | null }>({ schedule: null, employees: null });
  const [manual, setManual] = useState({ employees: [{ id: 'E1', name: '', role: '', skills: '' }],
                                         shifts: [{ id: 'S1', date: '', start: '09:00', end: '17:00', assignment: '', required_skills: '', employee_id: 'E1' }] });

  const [scenarios, setScenarios] = useState<{ id: string; name: string }[]>([]);
  useEffect(() => {
    api.domains().then(setDomains).catch((e) => toast(errorMessage(e), 'error'));
    api.scenarios().then(setScenarios).catch(() => {});
  }, []);

  async function validate() {
    setBusy(true);
    try {
      let data: RawDataset;
      if (source === 'demo') {
        const res = await fetch(`/demo-data/${org.domain}.json`).then((r) => (r.ok ? r.json() : null)).catch(() => null);
        data = res ?? { __demo: org.domain };
      } else if (source === 'json') {
        if (!raw) throw new Error('Choose a JSON file first.');
        data = { ...raw, organization: { ...(raw.organization ?? {}), ...pickOrg(org, raw.organization) } };
      } else if (source === 'csv') {
        if (!csv.schedule) throw new Error('Choose the schedule CSV first.');
        const r = await api.validateCsv(csv.schedule, csv.employees, { name: org.name || 'My organization', domain: org.domain });
        setRaw(r.dataset as RawDataset);
        setReport(r.report);
        setStep(3);
        return;
      } else {
        data = manualToDataset(org, manual);
      }
      if (data.__demo) {
        setReport(null);
        setRaw(data);
        setStep(3);
        return;
      }
      setRaw(data);
      setReport(await api.validate(data));
      setStep(3);
    } catch (e) {
      toast(errorMessage(e), 'error');
    } finally {
      setBusy(false);
    }
  }

  async function start() {
    setBusy(true);
    try {
      if (raw?.__demo) {
        const r = await api.loadDemo(raw.__demo);
        toast(r.report.summary);
        onDone(r.workspace);
      } else {
        const r = await api.loadDataset({ ...raw, source: source === 'csv' ? 'CSV upload' : source === 'json' ? 'JSON upload' : 'manual entry' });
        if (!r.workspace) throw new Error(r.report.summary);
        toast(r.report.warnings.length ? `${r.report.summary}` : 'Dataset successfully imported.', r.report.warnings.length ? 'warning' : 'success');
        onDone(r.workspace);
      }
    } catch (e) {
      toast(errorMessage(e), 'error');
    } finally {
      setBusy(false);
    }
  }

  const steps = ['Organization', 'Data source', 'Validate', 'Preview & start'];
  return (
    <div className="min-h-screen bg-slate-50 p-6">
      <div className="max-w-5xl mx-auto">
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Set up your workspace</h1>
            <p className="text-xs text-slate-500">ResQWork starts from your existing schedule. Nothing is changed until you approve a repair.</p>
          </div>
          {onCancel && <Button variant="ghost" onClick={onCancel}>Cancel</Button>}
        </div>
        <ol className="flex gap-2 mb-5" aria-label="Progress">
          {steps.map((s, i) => (
            <li key={s} className={`flex-1 text-xs px-3 py-2 rounded border ${step === i + 1 ? 'bg-white border-slate-900 font-semibold' : step > i + 1 ? 'bg-emerald-50 border-emerald-200 text-emerald-800' : 'bg-white border-slate-200 text-slate-500'}`}>
              {i + 1}. {s}
            </li>
          ))}
        </ol>

        {step === 1 && (
          <Card>
            <CardHeader title="Organization & industry" subtitle="The industry configures dashboards, terminology, KPIs and rules." />
            <CardBody className="p-4 space-y-4">
              <div className="grid sm:grid-cols-3 gap-3">
                <Field label="Organization name"><input className="input" value={org.name} onChange={(e) => setOrg({ ...org, name: e.target.value })} placeholder="e.g. St. Aster Hospital" /></Field>
                <Field label="Location"><input className="input" value={org.location} onChange={(e) => setOrg({ ...org, location: e.target.value })} /></Field>
                <Field label="Size"><input className="input" value={org.size} onChange={(e) => setOrg({ ...org, size: e.target.value })} placeholder="e.g. 350 beds / 120 engineers" /></Field>
              </div>
              <div className="grid sm:grid-cols-5 gap-2" role="radiogroup" aria-label="Industry">
                {domains.map((d) => (
                  <button key={d.id} role="radio" aria-checked={org.domain === d.id} onClick={() => setOrg({ ...org, domain: d.id })}
                          className={`text-left p-3 rounded border text-xs ${org.domain === d.id ? 'border-slate-900 bg-white shadow-xs' : 'border-slate-200 bg-white hover:border-slate-300'}`}>
                    <span style={{ color: d.accent }}><DomainIcon name={d.icon} className="w-4 h-4" /></span>
                    <span className="block font-semibold mt-1">{d.label}</span>
                    <span className="block text-slate-500 text-[11px]">{d.dashboardName}</span>
                  </button>
                ))}
              </div>
              <div className="flex justify-end"><Button variant="primary" onClick={() => setStep(2)}>Continue</Button></div>
            </CardBody>
          </Card>
        )}

        {step === 2 && (
          <Card>
            <CardHeader title="Existing schedule" subtitle="Choose how to provide employees, shifts and the current assignments." />
            <CardBody className="p-4 space-y-4">
              <div className="grid sm:grid-cols-4 gap-2">
                {([['demo', 'Demo dataset', Sparkles, 'Realistic sample data for this industry'], ['json', 'JSON upload', FileJson, 'Canonical ResQWork format'],
                   ['csv', 'CSV upload', FileSpreadsheet, 'Schedule CSV (+ optional employees CSV)'], ['manual', 'Manual entry', PenLine, 'Small teams: type it in']] as const).map(([id, label, Icon, hint]) => (
                  <button key={id} onClick={() => setSource(id)} aria-pressed={source === id}
                          className={`text-left p-3 rounded border ${source === id ? 'border-slate-900 bg-white shadow-xs' : 'border-slate-200 bg-white hover:border-slate-300'}`}>
                    <Icon className="w-4 h-4 text-slate-500" />
                    <span className="block text-xs font-semibold mt-1">{label}</span>
                    <span className="block text-[11px] text-slate-500">{hint}</span>
                  </button>
                ))}
              </div>
              {source === 'demo' && scenarios.length > 0 && (
                <div className="rounded border border-slate-200 bg-slate-50 p-3 text-xs space-y-2">
                  <p className="text-slate-700">Or load a small test scenario to check how repairs behave in edge cases:</p>
                  <div className="flex flex-wrap gap-2">
                    {scenarios.map((s) => (
                      <Button key={s.id} size="sm" disabled={busy} onClick={async () => {
                        setBusy(true);
                        try { const r = await api.loadScenario(s.id); toast(r.report.summary, r.report.warnings.length ? 'warning' : 'success'); onDone(r.workspace); }
                        catch (e) { toast(errorMessage(e), 'error'); } finally { setBusy(false); }
                      }}>{s.name}</Button>
                    ))}
                  </div>
                </div>
              )}
              {source === 'json' && (
                <Field label="Dataset JSON (see shared/schemas/dataset.schema.json)">
                  <input type="file" accept=".json,application/json" className="text-xs" onChange={async (e) => {
                    const f = e.target.files?.[0];
                    if (!f) return;
                    try { setRaw(JSON.parse(await f.text())); toast(`${f.name} read.`, 'info'); }
                    catch { toast('That file is not valid JSON.', 'error'); }
                  }} />
                </Field>
              )}
              {source === 'csv' && (
                <p className="text-[11px] text-slate-600">
                  Need an example? Download a <button type="button" className="underline text-[var(--accent)]" onClick={() => api.downloadTemplate('sample-schedule.csv').catch((e) => toast(errorMessage(e), 'error'))}>sample schedule CSV</button> and
                  {' '}<button type="button" className="underline text-[var(--accent)]" onClick={() => api.downloadTemplate('sample-employees.csv').catch((e) => toast(errorMessage(e), 'error'))}>sample employees CSV</button>.
                  Times are 24-hour (06:00, 14:00). After you start, open <b>Employees → Create employee logins</b> so your staff can sign in to their own dashboard.
                </p>
              )}
              {source === 'csv' && (
                <div className="grid sm:grid-cols-2 gap-3">
                  <Field label="Schedule CSV (required)">
                    <input type="file" accept=".csv,text/csv" className="text-xs" onChange={(e) => setCsv({ ...csv, schedule: e.target.files?.[0] ?? null })} />
                    <p className="text-[11px] text-slate-500 mt-1">Columns: shift_id, date, start, end, assignment, department, required_skills, employee_id, employee_name, role</p>
                  </Field>
                  <Field label="Employees CSV (optional)">
                    <input type="file" accept=".csv,text/csv" className="text-xs" onChange={(e) => setCsv({ ...csv, employees: e.target.files?.[0] ?? null })} />
                    <p className="text-[11px] text-slate-500 mt-1">Columns: id, name, role, department, skills, certifications, max_daily_hours, contracted_weekly_hours, max_weekly_hours</p>
                  </Field>
                </div>
              )}
              {source === 'manual' && <ManualForm value={manual} onChange={setManual} />}
              <div className="flex justify-between">
                <Button variant="ghost" onClick={() => setStep(1)}>Back</Button>
                <Button variant="primary" onClick={validate} disabled={busy}>{busy ? 'Validating…' : 'Validate data'}</Button>
              </div>
            </CardBody>
          </Card>
        )}

        {step === 3 && (
          <Card>
            <CardHeader title="Validation" subtitle="Records are checked one by one; bad records are reported, not silently dropped." />
            <CardBody className="p-4 space-y-3">
              {raw?.__demo ? (
                <p className="text-sm text-slate-700 flex items-center gap-2"><CheckCircle2 className="w-4 h-4 text-emerald-600" /> The {org.domain} demo dataset is pre-validated.</p>
              ) : report && <ReportView report={report} />}
              <div className="flex justify-between">
                <Button variant="ghost" onClick={() => setStep(2)}>Back</Button>
                <Button variant="primary" disabled={!raw?.__demo && report?.status === 'invalid'} onClick={() => setStep(4)}>Preview dataset</Button>
              </div>
            </CardBody>
          </Card>
        )}

        {step === 4 && (
          <Card>
            <CardHeader title="Preview dataset" subtitle="This becomes your starting schedule (v1.0)." />
            <CardBody className="p-4 space-y-4">
              {raw?.__demo ? <p className="text-sm text-slate-600">Demo data for {org.domain} will be loaded with its disruption presets.</p> : <Preview raw={raw} />}
              <div className="flex justify-between">
                <Button variant="ghost" onClick={() => setStep(3)}>Back</Button>
                <Button variant="action" size="lg" onClick={start} disabled={busy}>{busy ? 'Loading…' : 'Start with this schedule'}</Button>
              </div>
            </CardBody>
          </Card>
        )}
      </div>
    </div>
  );
}

type OrgForm = { name: string; domain: DomainId; location: string; size: string; timezone: string };
function pickOrg(org: OrgForm, existing: RawDataset['organization'] | null | undefined) {
  return { name: org.name || existing?.name || 'My organization', domain: org.domain, location: org.location || existing?.location,
           size: org.size || existing?.size, timezone: existing?.timezone || org.timezone };
}

function manualToDataset(org: OrgForm, m: ManualData): RawDataset {
  const split = (s: string) => s.split(/[;,]/).map((x) => x.trim()).filter(Boolean);
  return {
    organization: pickOrg(org, null),
    employees: m.employees.map((e) => ({ id: e.id, name: e.name, role: e.role || 'Staff', skills: split(e.skills) })),
    shifts: m.shifts.map((s) => ({ id: s.id, date: s.date, start: s.start, end: s.end, assignment: s.assignment || s.id, required_skills: split(s.required_skills) })),
    existing_schedule: m.shifts.filter((s) => s.employee_id).map((s) => ({ shift_id: s.id, employee_id: s.employee_id })),
  };
}

const Field = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <label className="block text-xs text-slate-600"><span className="block mb-1 font-medium">{label}</span>{children}</label>
);

function ReportView({ report }: { report: ValidationReport }) {
  const byCat = useMemo(() => {
    const m: Record<string, number> = {};
    [...report.errors, ...report.warnings].forEach((f) => { m[f.category] = (m[f.category] ?? 0) + 1; });
    return m;
  }, [report]);
  const Icon = report.status === 'valid' ? CheckCircle2 : report.status === 'invalid' ? XCircle : AlertTriangle;
  const tone = report.status === 'valid' ? 'text-emerald-700' : report.status === 'invalid' ? 'text-rose-700' : 'text-amber-700';
  return (
    <div className="space-y-3">
      <p className={`text-sm font-medium flex items-center gap-2 ${tone}`}><Icon className="w-4 h-4" /> {report.summary}</p>
      <div className="flex flex-wrap gap-2 text-[11px]">
        {Object.entries(report.stats).map(([k, v]) => <span key={k} className="px-2 py-1 rounded bg-slate-100 text-slate-700">{k.replace(/_/g, ' ')}: <b>{v}</b></span>)}
        {Object.entries(byCat).map(([k, v]) => <span key={k} className="px-2 py-1 rounded bg-amber-50 text-amber-800 border border-amber-200">{k.replace(/_/g, ' ')}: {v}</span>)}
      </div>
      {[...report.errors, ...report.warnings].length > 0 && (
        <ul className="max-h-64 overflow-auto divide-y divide-slate-100 border border-slate-200 rounded text-xs">
          {[...report.errors, ...report.warnings].map((f, i) => (
            <li key={i} className="px-3 py-1.5 flex gap-2">
              <span className={`font-mono text-[10px] uppercase ${f.severity === 'error' ? 'text-rose-600' : 'text-amber-600'}`}>{f.severity}</span>
              <span className="text-slate-700">{f.message}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Preview({ raw }: { raw: RawDataset | null }) {
  const emps = raw?.employees ?? [];
  const shifts = raw?.shifts ?? [];
  const assigned = new Map<string, string>((raw?.existing_schedule ?? []).map((a) => [a.shift_id, a.employee_id]));
  const names = new Map<string, string>(emps.map((e) => [e.id, e.name]));
  return (
    <div className="grid lg:grid-cols-2 gap-4">
      <div>
        <h3 className="text-xs font-semibold mb-2">Employees ({emps.length})</h3>
        <div className="max-h-72 overflow-auto border border-slate-200 rounded">
          <table className="w-full text-xs"><thead className="bg-slate-50 text-slate-500"><tr><th className="text-left px-2 py-1.5">Name</th><th className="text-left px-2">Role</th><th className="text-left px-2">Skills</th></tr></thead>
            <tbody>{emps.slice(0, 50).map((e) => <tr key={e.id} className="border-t border-slate-100"><td className="px-2 py-1">{e.name}</td><td className="px-2">{e.role}</td><td className="px-2 text-slate-500">{[...(e.skills ?? []), ...(e.certifications ?? [])].join(', ')}</td></tr>)}</tbody></table>
        </div>
      </div>
      <div>
        <h3 className="text-xs font-semibold mb-2">Shifts ({shifts.length})</h3>
        <div className="max-h-72 overflow-auto border border-slate-200 rounded">
          <table className="w-full text-xs"><thead className="bg-slate-50 text-slate-500"><tr><th className="text-left px-2 py-1.5">When</th><th className="text-left px-2">Assignment</th><th className="text-left px-2">Assigned</th></tr></thead>
            <tbody>{shifts.slice(0, 80).map((s) => <tr key={s.id} className="border-t border-slate-100"><td className="px-2 py-1 whitespace-nowrap">{s.date} {s.start}–{s.end}</td><td className="px-2">{s.assignment}</td><td className="px-2">{names.get(assigned.get(s.id) ?? '') ?? <span className="text-amber-600">open</span>}</td></tr>)}</tbody></table>
        </div>
      </div>
    </div>
  );
}

function ManualForm({ value, onChange }: { value: ManualData; onChange: (v: ManualData) => void }) {
  const upd = (kind: 'employees' | 'shifts', i: number, key: string, v: string) =>
    onChange(kind === 'employees'
      ? { ...value, employees: value.employees.map((r, j) => (j === i ? { ...r, [key]: v } : r)) }
      : { ...value, shifts: value.shifts.map((r, j) => (j === i ? { ...r, [key]: v } : r)) });
  const add = (kind: 'employees' | 'shifts') => onChange(kind === 'employees'
    ? { ...value, employees: [...value.employees, { id: `E${value.employees.length + 1}`, name: '', role: '', skills: '' }] }
    : { ...value, shifts: [...value.shifts, { id: `S${value.shifts.length + 1}`, date: '', start: '09:00', end: '17:00', assignment: '', required_skills: '', employee_id: '' }] });
  const del = (kind: 'employees' | 'shifts', i: number) => onChange(kind === 'employees'
    ? { ...value, employees: value.employees.filter((_, j) => j !== i) } : { ...value, shifts: value.shifts.filter((_, j) => j !== i) });
  return (
    <div className="space-y-4 text-xs">
      <div>
        <h3 className="font-semibold mb-1">Employees</h3>
        {value.employees.map((e, i) => (
          <div key={i} className="grid grid-cols-[4rem_1fr_1fr_1.5fr_auto] gap-2 mb-1.5">
            <input aria-label="ID" className="input" value={e.id} onChange={(x) => upd('employees', i, 'id', x.target.value)} />
            <input aria-label="Name" className="input" placeholder="Name" value={e.name} onChange={(x) => upd('employees', i, 'name', x.target.value)} />
            <input aria-label="Role" className="input" placeholder="Role" value={e.role} onChange={(x) => upd('employees', i, 'role', x.target.value)} />
            <input aria-label="Skills" className="input" placeholder="Skills (; separated)" value={e.skills} onChange={(x) => upd('employees', i, 'skills', x.target.value)} />
            <button aria-label="Remove employee" onClick={() => del('employees', i)} className="text-slate-400 hover:text-rose-600"><Trash2 className="w-3.5 h-3.5" /></button>
          </div>
        ))}
        <Button size="sm" icon={<Plus className="w-3 h-3" />} onClick={() => add('employees')}>Add employee</Button>
      </div>
      <div>
        <h3 className="font-semibold mb-1">Shifts (with current assignee)</h3>
        {value.shifts.map((s, i) => (
          <div key={i} className="grid grid-cols-[4rem_8rem_5rem_5rem_1fr_1fr_6rem_auto] gap-2 mb-1.5">
            <input aria-label="Shift ID" className="input" value={s.id} onChange={(x) => upd('shifts', i, 'id', x.target.value)} />
            <input aria-label="Date" type="date" className="input" value={s.date} onChange={(x) => upd('shifts', i, 'date', x.target.value)} />
            <input aria-label="Start" className="input" value={s.start} onChange={(x) => upd('shifts', i, 'start', x.target.value)} />
            <input aria-label="End" className="input" value={s.end} onChange={(x) => upd('shifts', i, 'end', x.target.value)} />
            <input aria-label="Assignment" className="input" placeholder="Assignment" value={s.assignment} onChange={(x) => upd('shifts', i, 'assignment', x.target.value)} />
            <input aria-label="Required skills" className="input" placeholder="Required skills" value={s.required_skills} onChange={(x) => upd('shifts', i, 'required_skills', x.target.value)} />
            <input aria-label="Employee ID" className="input" placeholder="Employee ID" value={s.employee_id} onChange={(x) => upd('shifts', i, 'employee_id', x.target.value)} />
            <button aria-label="Remove shift" onClick={() => del('shifts', i)} className="text-slate-400 hover:text-rose-600"><Trash2 className="w-3.5 h-3.5" /></button>
          </div>
        ))}
        <Button size="sm" icon={<Plus className="w-3 h-3" />} onClick={() => add('shifts')}>Add shift</Button>
      </div>
    </div>
  );
}

/** A dataset as uploaded or built here, before the server validates it (shape of shared/schemas/dataset.schema.json). */
interface RawDataset {
  __demo?: DomainId;
  organization?: { name?: string; domain?: DomainId; location?: string; size?: string; timezone?: string };
  employees?: { id: string; name: string; role?: string; skills?: string[]; certifications?: string[] }[];
  shifts?: { id: string; date: string; start: string; end: string; assignment?: string; required_skills?: string[] }[];
  existing_schedule?: { shift_id: string; employee_id: string }[];
  [key: string]: unknown;
}
interface ManualData {
  employees: { id: string; name: string; role: string; skills: string }[];
  shifts: { id: string; date: string; start: string; end: string; assignment: string; required_skills: string; employee_id: string }[];
}
