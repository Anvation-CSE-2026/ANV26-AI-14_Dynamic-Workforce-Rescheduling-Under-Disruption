// Structured what-if simulations (spec §19). Every run is a simulation: nothing is saved until the admin approves.
import { useState } from 'react';
import { api, errorMessage } from '../../api/client';
import type { Employee, Proposal, Simulation, SimulationAction } from '../../api/types';
import { Button } from '../common/Button';
import { Card, CardBody, CardHeader } from '../common/Card';
import { FlaskConical } from '../common/icons';
import { Chip, Notice, TimeInput } from '../common/ui';
import { isHHMM } from '../../lib/format';

export function WhatIfLab({ p, employees }: { p: Proposal; employees: Employee[] }) {
  const best = p.result.options.find((o) => o.option_id === p.result.recommended_option_id) ?? p.result.options[0];
  const slots = (p.problem?.affected_shifts ?? []).map((s) => s.shift_id);
  const firstSlot = best?.changes[0]?.shift_id ?? slots[0] ?? '';
  const [mode, setMode] = useState<'assign' | 'option' | 'move_shift' | 'add_employee'>('assign');
  const [shift, setShift] = useState(firstSlot);
  const [emp, setEmp] = useState('');
  const [optionId, setOptionId] = useState(p.result.options[1]?.option_id ?? '');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<Simulation | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const shiftIds = Array.from(new Set([...(best?.changes.map((c) => c.shift_id) ?? []), ...slots]));

  async function run() {
    let action: SimulationAction;
    if (mode === 'assign') action = { type: 'assign', shift_id: shift, employee_id: emp };
    else if (mode === 'option') action = { type: 'option', option_id: optionId };
    else if (mode === 'move_shift') action = { type: 'move_shift', shift_id: shift, start, end };
    else action = { type: 'add_employee' };
    setBusy(true); setErr(null); setRes(null);
    try { setRes(await api.simulate(p.id, action)); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  const ready = mode === 'assign' ? !!shift && !!emp : mode === 'option' ? !!optionId
    : mode === 'move_shift' ? !!shift && isHHMM(start) && isHHMM(end) : true;
  const label = (id: string) => {
    const c = best?.changes.find((x) => x.shift_id === id) ?? p.problem?.affected_shifts.find((x) => x.shift_id === id);
    return c ? `${c.assignment} · ${c.date} ${c.start}–${c.end}` : id;
  };

  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-1.5"><FlaskConical className="w-4 h-4 text-slate-400" />What-if lab</span>}
                  subtitle="Simulate a decision before you make it. Nothing is saved." />
      <CardBody className="p-4 space-y-3 text-xs">
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="What-if type">
          {([['assign', 'Assign someone'], ['option', 'Choose another option'], ['move_shift', 'Move the shift'], ['add_employee', 'Add one employee']] as const).map(([k, l]) => (
            <button key={k} type="button" onClick={() => { setMode(k); setRes(null); }} aria-pressed={mode === k}
                    className={`px-2 py-1 rounded border ${mode === k ? 'bg-slate-900 text-white border-slate-900' : 'border-slate-200 text-slate-600 hover:bg-slate-50'}`}>{l}</button>
          ))}
        </div>
        {(mode === 'assign' || mode === 'move_shift') && (
          <select aria-label="Shift" className="input w-full" value={shift} onChange={(e) => setShift(e.target.value)}>
            {shiftIds.map((id) => <option key={id} value={id}>{label(id)}</option>)}
          </select>
        )}
        {mode === 'assign' && (
          <select aria-label="Employee" className="input w-full" value={emp} onChange={(e) => setEmp(e.target.value)}>
            <option value="">Choose an employee…</option>
            {employees.filter((e) => e.status !== 'inactive').map((e) => <option key={e.id} value={e.id}>{e.name} · {e.role}</option>)}
          </select>
        )}
        {mode === 'option' && (
          <select aria-label="Option" className="input w-full" value={optionId} onChange={(e) => setOptionId(e.target.value)}>
            {p.result.options.filter((o) => o.option_id !== best?.option_id).map((o) => <option key={o.option_id} value={o.option_id}>{o.label}: {o.title}</option>)}
          </select>
        )}
        {mode === 'move_shift' && (
          <div className="grid grid-cols-2 gap-2">
            <TimeInput value={start} onChange={setStart} ariaLabel="New start (HH:MM)" />
            <TimeInput value={end} onChange={setEnd} ariaLabel="New end (HH:MM)" />
          </div>
        )}
        {mode === 'option' && p.result.options.length < 2 && <p className="text-slate-500">This repair has only one option.</p>}
        <Button size="sm" variant="primary" disabled={!ready || busy} onClick={run}>{busy ? 'Simulating…' : 'Simulate'}</Button>
        {err && <Notice tone="error">{err}</Notice>}
        {res && (
          <div className="space-y-2 rounded-md border border-slate-200 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Chip tone={res.feasible ? 'green' : 'red'}>{res.feasible ? 'Valid' : 'Breaks hard constraints'}</Chip>
              <Chip>Not saved</Chip>
            </div>
            <p className="text-slate-800">{res.summary}</p>
            {res.conflicts_introduced.length > 0 && <ul className="list-disc pl-4 text-rose-700">{res.conflicts_introduced.map((c) => <li key={c}>{c}</li>)}</ul>}
            <dl className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <div><dt className="text-slate-500">Changes</dt><dd className="font-semibold">{res.changes_count}</dd></div>
              <div><dt className="text-slate-500">Overtime</dt><dd className="font-semibold">{res.overtime_added} h</dd></div>
              <div><dt className="text-slate-500">Fairness</dt><dd className="font-semibold">{res.fairness_before ?? '—'} → {res.fairness_after ?? '—'}</dd></div>
              <div><dt className="text-slate-500">Score</dt><dd className="font-semibold">{res.optimization_score ?? '—'} <span className="text-slate-400 font-normal">vs {res.baseline_score ?? '—'}</span></dd></div>
            </dl>
            {res.workload.length > 0 && (
              <div><p className="text-slate-500">Workload change</p>
                <ul>{res.workload.map((w) => <li key={w.employee_id}>{w.employee_name}: {w.before} h → {w.after} h</li>)}</ul></div>
            )}
          </div>
        )}
      </CardBody>
    </Card>
  );
}
