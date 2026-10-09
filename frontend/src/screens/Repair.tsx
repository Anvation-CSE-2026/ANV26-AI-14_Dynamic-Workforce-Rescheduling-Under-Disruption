// Repair Centre. Reads top to bottom the way the decision is made:
// Problem → Impact → Constraint analysis → Recommended repair & alternatives → Why → Impact of the chosen repair
// → Human control (Approve / Reject / Compare / View details). Nothing is published without an explicit approval.
import React, { useEffect, useMemo, useState } from 'react';
import {
  ArrowRight, CheckCircle2, XCircle, Sparkles, AlertTriangle, HelpCircle, FlaskConical, ShieldCheck, Info, Columns3,
  ChevronDown, ChevronUp, CircleDot,
} from '../components/common/icons';
import { api, errorMessage } from '../api/client';
import type { Employee, Proposal, RepairOption, WhatIfResponse } from '../api/types';
import { Button } from '../components/common/Button';
import { Card, CardBody, CardHeader } from '../components/common/Card';
import { StatusIndicator } from '../components/common/Badge';
import { Modal } from '../components/common/Modal';
import { EmptyState, ErrorState, Spinner } from '../components/common/States';
import { Why } from '../components/common/Why';
import { ConstraintChecklist, UnresolvedPanel } from '../components/repair/ConstraintAnalysis';
import { WhatIfLab } from '../components/repair/WhatIfLab';
import { whyFairness, whyImpact, whyRecommended, whyRejected, whyRemoved, whySelected } from '../components/repair/reasons';
import { useDomain } from '../lib/domain';
import { fmtDay, impactTone, REASON_LABEL, titleCase } from '../lib/format';
import { useToast } from '../lib/toast';

const letter = (label: string) => label.replace(/^Option\s+/i, '');
const titleOf = (o: RepairOption) => (o.impact.unfilled_shifts ? `Partial repair (leaves ${o.impact.unfilled_shifts} uncovered)` : o.title);

export function Repair({ proposalId, onChanged, onGoDashboard }: {
  proposalId?: string;
  onChanged: () => void;
  onGoDashboard: () => void;
}) {
  const { t, config } = useDomain();
  const toast = useToast();
  const [p, setP] = useState<Proposal | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [sel, setSel] = useState<string>();
  const [approveOpen, setApproveOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [compareOpen, setCompareOpen] = useState(false);
  const [details, setDetails] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [whatIf, setWhatIf] = useState('');
  const [delta, setDelta] = useState<WhatIfResponse | null>(null);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [whyNot, setWhyNot] = useState<{ name: string; text: string } | null>(null);

  async function load(id?: string) {
    setLoading(true);
    setError(undefined);
    try {
      const prop = id ? await api.proposal(id) : await api.latestProposal();
      setP(prop);
      setSel(prop?.approved_option ?? prop?.result.recommended_option_id ?? prop?.result.options[0]?.option_id);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { load(proposalId); }, [proposalId]);
  useEffect(() => { api.employees().then(setEmployees).catch(() => {}); }, []);

  const opt = useMemo(() => p?.result.options.find((o) => o.option_id === sel), [p, sel]);

  if (loading) return <Spinner label="Loading repair…" />;
  if (error) return <ErrorState message={error} onRetry={() => load(proposalId)} />;
  if (!p) return (
    <Card><EmptyState title="No repair yet" hint="Simulate or report a disruption, or repair a detected schedule conflict, from the command center."
                      action={<Button variant="primary" onClick={onGoDashboard}>Go to {config?.dashboardName ?? 'dashboard'}</Button>} /></Card>
  );

  const r = p.result;
  const pending = p.status === 'pending';
  const unresolved = r.unresolved ?? [];
  const feasible = r.status === 'OPTIMAL' || r.status === 'FEASIBLE';
  const partial = !!opt && opt.impact.unfilled_shifts > 0;
  const expl = opt ? p.explanations[opt.option_id] : undefined;
  const label = (k: string, f: string) => config?.constraintLabels?.[k] ?? f;
  const shiftWord = t('shift', 'shift').toLowerCase();
  const hard = r.hard_constraints ?? [];

  async function runWhatIf(e: React.FormEvent) {
    e.preventDefault();
    if (!whatIf.trim() || !p) return;
    setBusy('whatif');
    try {
      const res = await api.whatIf(p.id, whatIf);
      setDelta(res);
      if (res.proposal) {
        toast(`What-if solved: ${res.scenario?.summary ?? ''}`, 'info');
        setP(res.proposal);
        setSel(res.proposal.result.recommended_option_id ?? res.proposal.result.options[0]?.option_id);
        onChanged();
      } else {
        toast(res.scenario?.issues?.[0]?.message ?? 'Could not understand that scenario.', 'warning');
      }
    } catch (err) {
      toast(errorMessage(err), 'error');
    } finally {
      setBusy(null);
    }
  }

  async function askWhyNot(name: string) {
    if (!name) return;
    setBusy('whynot');
    try {
      const res = await api.voice(`why not ${name}`);
      setWhyNot({ name, text: res.text });
    } catch (e) {
      toast(errorMessage(e), 'error');
    } finally {
      setBusy(null);
    }
  }

  const statusLabel = p.status === 'approved' ? 'Approved and published' : p.status === 'rejected' ? 'Rejected'
    : feasible ? 'Awaiting your approval' : 'No feasible repair: decision needed';
  const problemItems = p.problem?.items ?? r.disruptions.map((d) => ({
    kind: 'absence', title: `${employees.find((e) => e.id === d.employee_id)?.name ?? d.employee_id} unavailable`,
    detail: `${d.date} ${d.start ?? ''}–${d.end ?? ''}`, hard_constraint: 'Availability', shift_ids: [] as string[] }));

  return (
    <div className="space-y-5">
      {/* Header + human control */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Repair centre</h2>
          <p className="text-xs text-slate-500">
            Solved by {r.solver} in {r.solve_ms} ms{p.scenario && <> · what-if: <i>{p.scenario}</i></>}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusIndicator status={p.status === 'approved' ? 'healthy' : p.status === 'rejected' ? 'neutral' : feasible ? 'info' : 'critical'} label={statusLabel} />
          {r.options.length > 1 && <Button icon={<Columns3 className="w-3.5 h-3.5" />} onClick={() => setCompareOpen(true)}>Compare</Button>}
          {opt && <Button icon={details ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />} onClick={() => setDetails((d) => !d)}>
            {details ? 'Hide details' : 'View details'}</Button>}
          {pending && (
            <Button variant="destructive" icon={<XCircle className="w-3.5 h-3.5" />} onClick={() => setRejectOpen(true)}>Reject</Button>
          )}
          {pending && opt && (
            <Button variant={partial ? 'outline' : 'primary'} icon={<CheckCircle2 className="w-3.5 h-3.5" />} onClick={() => setApproveOpen(true)}>
              {partial ? `Override: approve partial option ${letter(opt.label)}` : `Approve repair (option ${letter(opt.label)})`}</Button>
          )}
        </div>
      </div>

      <Flow p={p} feasible={feasible} />

      {/* Problem + impact */}
      <div className="grid lg:grid-cols-[1.2fr_1fr] gap-5 [&>*]:min-w-0">
        <Card>
          <CardHeader title="Problem" subtitle="What went wrong" />
          <ul className="divide-y divide-slate-100 text-xs">
            {problemItems.map((i, k) => (
              <li key={k} className="px-4 py-2.5 flex items-start gap-2">
                <AlertTriangle className="w-3.5 h-3.5 text-rose-500 mt-0.5 shrink-0" />
                <div>
                  <p className="font-medium text-slate-900">{i.title}</p>
                  <p className="text-slate-600">{i.detail}</p>
                  <Why text={`This breaks the hard constraint "${i.hard_constraint}", so the affected ${shiftWord} must be re-covered or reported as unresolved.`}>
                    <span className="text-[11px] text-rose-700">Violates: {i.hard_constraint}</span>
                  </Why>
                </div>
              </li>
            ))}
          </ul>
        </Card>
        <Card>
          <CardHeader title="Impact" subtitle={`${t('shifts', 'Shifts')} that need new cover`} />
          <ul className="divide-y divide-slate-100 text-xs">
            {(p.problem?.affected_shifts ?? r.disrupted_shifts.map((s) => ({ shift_id: s, assignment: s, date: '', start: '', end: '', priority: '' }))).map((s) => {
              const u = unresolved.find((x) => x.shift_id === s.shift_id);
              return (
                <li key={s.shift_id} className="px-4 py-2 flex items-center gap-2">
                  <span className="flex-1"><b className="font-medium">{s.assignment}</b>
                    {s.date && <span className="text-slate-500"> · {fmtDay(s.date)} {s.start}–{s.end}</span>}
                    {s.priority === 'critical' && <span className="ml-1.5 text-[10px] text-rose-600">critical</span>}</span>
                  {u ? <Why text={u.summary}><span className="text-rose-600 font-medium">Unresolved</span></Why>
                     : <span className={feasible ? 'text-emerald-700' : 'text-slate-500'}>{feasible ? 'Covered by repair' : 'Covered'}</span>}
                </li>
              );
            })}
          </ul>
          {opt && <p className="px-4 py-2 border-t border-slate-100 text-[11px] text-slate-500">
            {opt.impact.employees_affected} {opt.impact.employees_affected === 1 ? 'person' : 'people'} affected · {opt.impact.departments_affected.join(', ') || '—'}</p>}
        </Card>
      </div>

      <ConstraintChecklist hard={hard} soft={r.soft_objectives ?? []} unresolvedCount={unresolved.length} />

      <UnresolvedPanel items={unresolved} />

      {(p.relaxation || (!feasible && r.options.length > 0)) && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs space-y-1" role="note">
          {!feasible && r.options.length > 0 && <p className="text-amber-900 flex gap-2"><Info className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            A partial repair below covers what can legally be covered and leaves the shift(s) above open. It is <b>not</b> a valid full repair; approving it is a manual override.</p>}
          {p.relaxation && <p className="text-amber-900 flex gap-2"><Info className="w-3.5 h-3.5 shrink-0 mt-0.5" />What-if, not applied: {p.relaxation.message}</p>}
        </div>
      )}

      {r.options.length === 0 ? (
        !unresolved.length && <Card><EmptyState title="Nothing to repair" hint={r.infeasibility_reasons.join(' ') || 'No scheduled shift is affected.'} /></Card>
      ) : (
        <>
          <Card>
            <CardHeader title={feasible ? 'Recommended repair and alternatives' : 'Best partial repair'} subtitle={p.comparison?.headline ?? 'Every option passed the full hard-constraint check'} />
            <div className="overflow-x-auto">
              <table className="w-full text-xs" aria-label="Repair options">
                <thead className="bg-slate-50 text-slate-500">
                  <tr>
                    <th className="text-left font-medium px-4 py-2">Option</th>
                    <th className="text-right font-medium px-2">Scheduling impact</th>
                    <th className="text-right font-medium px-2">Changes</th>
                    <th className="text-right font-medium px-2">People affected</th>
                    <th className="text-right font-medium px-2">Overtime</th>
                    <th className="text-right font-medium px-2">Fairness</th>
                    <th className="text-right font-medium px-2">Uncovered</th>
                    <th className="px-4" />
                  </tr>
                </thead>
                <tbody>
                  {r.options.map((o) => (
                    <OptionRow key={o.option_id} p={p} o={o} active={o.option_id === sel} recommended={o.option_id === r.recommended_option_id}
                               approved={p.approved_option === o.option_id} onSelect={() => setSel(o.option_id)} />
                  ))}
                  {r.baseline && (
                    <tr className="border-t border-slate-100 text-slate-400">
                      <td className="px-4 py-2">
                        <Why text="A greedy rebuild that ignores the existing schedule, shown only to measure how much the repair preserves.">
                          <span>Rebuilding from scratch (reference)</span></Why></td>
                      <td className="text-right px-2">—</td>
                      <td className="text-right px-2 tabular-nums">{r.baseline.assignments_changed}</td>
                      <td className="text-right px-2 tabular-nums">{r.baseline.employees_affected}</td>
                      <td className="text-right px-2">—</td><td className="text-right px-2">—</td>
                      <td className="text-right px-2 tabular-nums">{r.baseline.uncovered}</td><td />
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>

          {opt && (
            <div className="grid grid-cols-1 xl:grid-cols-[1.3fr_1fr] gap-5 [&>*]:min-w-0">
              <div className="space-y-5">
                <Card>
                  <CardHeader title={`Option ${letter(opt.label)}: ${titleOf(opt)}`} subtitle="Before → after. Only what changes is shown." />
                  <CardBody className="p-0">
                    {opt.changes.length === 0 ? <EmptyState title="No changes needed" /> : (
                      <ul className="divide-y divide-slate-100">
                        {opt.changes.map((c) => {
                          const ev = opt.selected.find((s) => s.employee_id === c.to_employee_id && s.shift_id === c.shift_id)
                            ?? opt.selected.find((s) => s.employee_id === c.to_employee_id);
                          return (
                            <li key={c.shift_id} className="px-4 py-3 text-xs">
                              <p className="text-slate-500">{fmtDay(c.date)} · {c.start}–{c.end}{c.department ? ` · ${c.department}` : ''}</p>
                              <p className="font-medium text-slate-900 mt-0.5">{c.assignment}</p>
                              <div className="mt-1.5 flex items-center gap-2 flex-wrap">
                                <Why text={whyRemoved(p, opt, c)}>
                                  <span className="px-2 py-0.5 rounded bg-rose-50 text-rose-700 border border-rose-200 line-through">{c.from_employee_name ?? 'Open'}</span>
                                </Why>
                                <ArrowRight className="w-3.5 h-3.5 text-slate-400" />
                                {c.kind === 'uncovered'
                                  ? <Why text={unresolved.find((u) => u.shift_id === c.shift_id)?.summary ?? 'Nobody can legally cover this shift.'}>
                                      <span className="px-2 py-0.5 rounded bg-amber-50 text-amber-800 border border-amber-200">Stays uncovered</span></Why>
                                  : <Why text={whySelected(ev, c)}>
                                      <span className="px-2 py-0.5 rounded bg-emerald-50 text-emerald-800 border border-emerald-200 font-medium">{c.to_employee_name}</span></Why>}
                              </div>
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </CardBody>
                  <div className="px-4 py-2.5 text-[11px] text-slate-500 border-t border-slate-100">
                    <Why text={whyImpact(opt.impact)}>
                      <span>{opt.impact.horizon_shifts - opt.impact.assignments_changed} other {shiftWord}s stay exactly as they were ({opt.impact.preservation_rate}% preserved)</span>
                    </Why>
                    {r.baseline && <> · rebuilding would change {r.baseline.assignments_changed}</>}
                  </div>
                </Card>

                {details && <Evidence p={p} opt={opt} t={t} />}
              </div>

              <div className="space-y-5">
                <Card>
                  <CardHeader title={<span className="flex items-center gap-1.5"><Sparkles className="w-4 h-4 text-[var(--accent)]" />Why this repair?</span>}
                              subtitle={expl ? (expl.source === 'llm' ? 'AI-written from solver facts, grounding-checked' : 'Generated from solver facts') : undefined} />
                  <CardBody className="p-4 text-xs space-y-3">
                    {expl ? (
                      <>
                        <p className="text-sm font-medium text-slate-900">{expl.headline}</p>
                        <ul className="space-y-1.5 list-disc pl-4 text-slate-700">{expl.points.map((pt, i) => <li key={i}>{pt.text}</li>)}</ul>
                        {expl.why_not_others.length > 0 && (
                          <div>
                            <p className="font-semibold text-slate-700 mb-1">Why not others</p>
                            <ul className="space-y-1 list-disc pl-4 text-slate-600">{expl.why_not_others.map((pt, i) => <li key={i}>{pt.text}</li>)}</ul>
                          </div>
                        )}
                        {expl.grounding_warnings.length > 0 && <p className="text-amber-700">Note: {expl.grounding_warnings.join(' ')}</p>}
                      </>
                    ) : <p className="text-slate-500">{opt.note ?? 'No explanation available.'}</p>}
                  </CardBody>
                </Card>

                <Card>
                  <CardHeader title="Impact of this repair" />
                  <CardBody className="p-4 grid grid-cols-2 gap-2 text-xs">
                    <Metric label="Assignments changed" value={opt.impact.assignments_changed} why={whyImpact(opt.impact)} />
                    <Metric label="People affected" value={opt.impact.employees_affected}
                            why={`Everyone whose schedule changes in this option, including the people who move. ${opt.selected.map((s) => s.employee_name).join(', ') || 'Nobody'} take on new work.`} />
                    <Metric label="Overtime added" value={`${opt.impact.overtime_hours_added}h`} tone={opt.impact.overtime_hours_added ? 'warning' : 'healthy'}
                            why={opt.impact.overtime_hours_added ? `Hours above contract created by this option: ${opt.selected.filter((s) => s.overtime_hours_added).map((s) => `${s.employee_name} +${s.overtime_hours_added}h`).join(', ')}.` : 'Nobody goes above their contracted hours.'} />
                    <Metric label="Fairness" value={opt.fairness.fairness_score} why={whyFairness(opt.fairness)} />
                    <Metric label="Coverage" value={`${opt.impact.skill_coverage_pct}%`} tone={opt.impact.unfilled_shifts ? 'critical' : 'healthy'}
                            why={`Share of upcoming ${shiftWord}s staffed by a fully qualified person after this repair; ${opt.impact.unfilled_shifts} left uncovered.`} />
                    <Metric label="Hard constraints" value={`${hard.length - (opt.impact.unfilled_shifts ? 1 : 0)}/${hard.length}`} tone={opt.impact.unfilled_shifts ? 'critical' : 'healthy'}
                            why={opt.impact.unfilled_shifts ? 'Every rule holds except mandatory coverage: the uncovered shift is reported, not filled illegally.' : 'All hard constraints are satisfied; the validator re-checked the whole schedule.'} />
                    <Metric label="Scheduling impact" value={`${opt.impact.impact_score}%`} tone={impactTone(opt.impact.impact_level)} why={whyImpact(opt.impact)} />
                    <Metric label="Problems resolved" value={`${(p.problem?.items.length ?? r.disrupted_shifts.length) - unresolved.length}/${p.problem?.items.length ?? r.disrupted_shifts.length}`}
                            tone={unresolved.length ? 'critical' : 'healthy'} why="Problems from the Problem section that this option fully resolves." />
                  </CardBody>
                </Card>

                <Card>
                  <CardHeader title={<span className="flex items-center gap-1.5"><HelpCircle className="w-4 h-4 text-slate-400" />Why not someone else?</span>} />
                  <CardBody className="p-4 space-y-2 text-xs">
                    <label htmlFor="whynot" className="sr-only">Pick a person</label>
                    <select id="whynot" className="input w-full" defaultValue="" onChange={(e) => askWhyNot(e.target.value)}>
                      <option value="" disabled>Pick someone…</option>
                      {employees.map((e) => <option key={e.id} value={e.name}>{e.name} · {e.role}</option>)}
                    </select>
                    {busy === 'whynot' && <Spinner label="Checking…" />}
                    {whyNot && busy !== 'whynot' && <p className="rounded bg-slate-50 border border-slate-200 p-2.5 text-slate-700"><b>{whyNot.name}:</b> {whyNot.text}</p>}
                  </CardBody>
                </Card>

                {pending && (
                  <Card>
                    <CardHeader title={<span className="flex items-center gap-1.5"><FlaskConical className="w-4 h-4 text-slate-400" />What-if</span>} subtitle="Re-solve with a changed assumption; nothing is published" />
                    <CardBody className="p-4 space-y-2 text-xs">
                      <form onSubmit={runWhatIf} className="flex gap-2">
                        <label htmlFor="whatif" className="sr-only">What-if scenario</label>
                        <input id="whatif" className="input flex-1 min-w-0" value={whatIf} onChange={(e) => setWhatIf(e.target.value)}
                               placeholder={'e.g. "allow overtime", "don\'t use ' + (opt.selected[0]?.employee_name.split(' ')[0] ?? 'Neha') + '"'} />
                        <Button type="submit" disabled={busy === 'whatif'}>{busy === 'whatif' ? 'Solving…' : 'Run'}</Button>
                      </form>
                      <div className="flex flex-wrap gap-1.5">
                        {['allow overtime', 'minimize overtime', 'prioritize fairness', ...(opt.selected[0] ? [`don't use ${opt.selected[0].employee_name}`] : [])].map((s) => (
                          <button key={s} type="button" onClick={() => setWhatIf(s)} className="px-2 py-0.5 rounded border border-slate-200 text-slate-600 hover:bg-slate-50">{s}</button>
                        ))}
                      </div>
                      {delta?.delta && (
                        <p className="text-slate-600 rounded bg-slate-50 border border-slate-200 p-2">
                          {delta.delta.comparable && delta.delta.delta
                            ? Object.entries(delta.delta.delta).map(([k, v]) => `${titleCase(k)} ${v > 0 ? '+' : ''}${v}`).join(', ')
                            : delta.delta.message}
                        </p>
                      )}
                    </CardBody>
                  </Card>
                )}
                {pending && <WhatIfLab p={p} employees={employees} />}

                <Card>
                  <CardHeader title={<span className="flex items-center gap-1.5"><ShieldCheck className="w-4 h-4 text-emerald-600" />Policy rules applied</span>}
                              subtitle={`Policy mode: ${p.policy.mode}`} />
                  <ul className="divide-y divide-slate-100 text-xs">
                    {p.policy.constraints.slice(0, 8).map((c, i) => (
                      <li key={i} className="px-4 py-2">
                        <Why text={<>“{c.quote}”<br />{c.source}</>}>
                          <b className="font-medium">{label(c.type, titleCase(c.type))}</b></Why>: {String(c.value)}{c.unit ? ` ${c.unit}` : ''}
                        <span className={`ml-1.5 text-[10px] ${c.severity === 'hard' ? 'text-rose-600' : 'text-slate-500'}`}>{c.severity === 'hard' ? 'must' : 'prefer'}</span>
                        <p className="text-slate-500">{c.source}</p>
                      </li>
                    ))}
                    {p.policy.conflicts.map((c, i) => <li key={`k${i}`} className="px-4 py-2 text-amber-700">{c}</li>)}
                    {p.policy.constraints.length === 0 && <li className="px-4 py-3 text-slate-500">Base rules only (no policy documents loaded).</li>}
                  </ul>
                </Card>
              </div>
            </div>
          )}
        </>
      )}

      <ApproveModal open={approveOpen} onClose={() => setApproveOpen(false)} option={opt} partial={partial}
                    unresolved={unresolved.map((u) => u.summary)}
                    onApprove={async (notes, allowPartial) => {
                      try {
                        const res = await api.approve(p.id, opt!.option_id, notes, allowPartial);
                        toast(`Schedule ${res.version.tag} published. ${res.notifications.length} ${t('employee', 'employee').toLowerCase()}(s) notified.`);
                        setApproveOpen(false);
                        onChanged();
                        load(p.id);
                      } catch (e) { toast(errorMessage(e), 'error'); }
                    }} />
      <Modal isOpen={rejectOpen} onClose={() => setRejectOpen(false)} title="Reject this repair?" subtitle="The current schedule stays as it is; the problem remains open."
             footer={<><Button onClick={() => setRejectOpen(false)}>Cancel</Button>
               <Button variant="destructive" onClick={async () => {
                 const reason = (document.getElementById('reject-reason') as HTMLInputElement)?.value ?? '';
                 try { await api.reject(p.id, reason); toast('Repair rejected. The schedule is unchanged.', 'info'); setRejectOpen(false); onChanged(); load(p.id); }
                 catch (e) { toast(errorMessage(e), 'error'); }
               }}>Reject repair</Button></>}>
        <label className="block text-xs text-slate-600">Reason (optional, kept in the audit log)
          <input id="reject-reason" className="input w-full mt-1" placeholder="e.g. the replacement is covering another unit" />
        </label>
      </Modal>
      <CompareModal open={compareOpen} onClose={() => setCompareOpen(false)} p={p} onPick={(id) => { setSel(id); setCompareOpen(false); }} />
    </div>
  );
}

/** Where this repair is in the decision flow. */
function Flow({ p, feasible }: { p: Proposal; feasible: boolean }) {
  const steps = ['Disruption', 'Impact detected', 'Constraints validated', 'Candidates generated',
    feasible ? 'Best repair recommended' : 'No feasible repair', 'Human approval', 'Schedule updated'];
  const reached = p.status === 'approved' ? 7 : p.status === 'rejected' ? 6 : feasible ? 5 : 5;
  return (
    <ol className="flex flex-wrap items-center gap-x-1 gap-y-1 text-[11px]" aria-label="Repair progress">
      {steps.map((s, i) => {
        const done = i < reached;
        const bad = !feasible && i === 4;
        return (
          <li key={s} className="flex items-center gap-1">
            <span className={`flex items-center gap-1 px-2 py-0.5 rounded-full border ${bad ? 'border-rose-300 bg-rose-50 text-rose-700'
              : done ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-slate-200 bg-white text-slate-500'}`}>
              {bad ? <AlertTriangle className="w-3 h-3" /> : done ? <CheckCircle2 className="w-3 h-3" /> : <CircleDot className="w-3 h-3" />}{s}
            </span>
            {i < steps.length - 1 && <span className="text-slate-300" aria-hidden>›</span>}
          </li>
        );
      })}
    </ol>
  );
}

function Evidence({ p, opt, t }: { p: Proposal; opt: RepairOption; t: (k: string, f?: string) => string }) {
  const r = p.result;
  return (
    <>
      {opt.selected.length > 0 && (
        <Card>
          <CardHeader title="Details: why these people (computed by the solver)" subtitle="Hours, rest and qualifications checked against every rule" />
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-slate-500 bg-slate-50"><tr>
                <th className="text-left font-medium px-4 py-1.5">{t('employee', 'Employee')}</th>
                <th className="text-left font-medium px-2">Covers</th>
                <th className="text-right font-medium px-2">Weekly hours</th>
                <th className="text-right font-medium px-2">Rest before</th>
                <th className="text-left font-medium px-2">{t('skills', 'Skills')}</th>
                <th className="text-right font-medium px-4">Changes (30d)</th>
              </tr></thead>
              <tbody>{opt.selected.map((s) => (
                <tr key={s.employee_id + s.shift_id} className="border-t border-slate-100">
                  <td className="px-4 py-2 font-medium">{s.employee_name}</td>
                  <td className="px-2 text-slate-600 max-w-[14rem] truncate" title={s.covers}>{s.covers}</td>
                  <td className="px-2 text-right tabular-nums">{s.weekly_hours_before} → <b className={s.overtime_hours_added ? 'text-rose-600' : ''}>{s.weekly_hours_after}</b> / {s.contracted_weekly_hours}</td>
                  <td className="px-2 text-right tabular-nums">{s.rest_hours_before_shift != null ? `${s.rest_hours_before_shift}h` : '—'}</td>
                  <td className="px-2">{s.skills_match ? <span className="text-emerald-700">✓ {s.matched_skills.join(', ') || 'none required'}</span> : <span className="text-rose-600">missing</span>}</td>
                  <td className="px-4 text-right tabular-nums">{s.previous_changes_30d}</td>
                </tr>))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      {r.rejected.length > 0 && (
        <Card>
          <CardHeader title="Details: considered and ruled out" subtitle="Hard-rule failures and measured trade-offs, never AI guesses" />
          <ul className="divide-y divide-slate-100 text-xs">
            {r.rejected.slice(0, 12).map((x, i) => (
              <li key={i} className="px-4 py-2 flex items-start gap-3">
                <span className="w-28 shrink-0 font-medium text-slate-800 truncate">{x.employee_name}</span>
                <Why text={whyRejected(x)}>
                  <span className="shrink-0 px-1.5 py-0.5 rounded bg-slate-100 text-slate-700 text-[10px]">{REASON_LABEL[x.reason_code] ?? titleCase(x.reason_code)}</span>
                </Why>
                <span className="text-slate-600">{x.detail}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}

function OptionRow({ p, o, active, recommended, approved, onSelect }: {
  p: Proposal; o: RepairOption; active: boolean; recommended: boolean; approved: boolean; onSelect: () => void;
}) {
  return (
    <tr onClick={onSelect} className={`border-t border-slate-100 cursor-pointer ${active ? 'bg-[color-mix(in_srgb,var(--accent)_8%,white)]' : 'hover:bg-slate-50'}`}
        aria-selected={active}>
      <td className="px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span className={`w-6 h-6 shrink-0 rounded grid place-items-center text-[11px] font-bold ${active ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-700'}`}>{letter(o.label)}</span>
          <div>
            <p className="font-medium text-slate-900 flex items-center gap-1.5 flex-wrap">
              {recommended && o.impact.unfilled_shifts === 0 ? (
                <Why text={whyRecommended(p, o)}><span>{titleOf(o)}</span></Why>) : titleOf(o)}
              {recommended && o.impact.unfilled_shifts === 0 && o.title !== 'Recommended' && (
                <Why text={whyRecommended(p, o)}><span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--accent)] text-white">Recommended</span></Why>)}
              
              {approved && <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-600 text-white">Approved</span>}
            </p>
            <p className="text-[10px] text-slate-500">{o.goal}</p>
          </div>
        </div>
      </td>
      <td className="text-right px-2"><Why text={whyImpact(o.impact)}><StatusIndicator size="sm" status={impactTone(o.impact.impact_level)} label={`${o.impact.impact_score}% ${o.impact.impact_level}`} /></Why></td>
      <td className="text-right px-2 tabular-nums">{o.impact.assignments_changed}</td>
      <td className="text-right px-2 tabular-nums">{o.impact.employees_affected}</td>
      <td className={`text-right px-2 tabular-nums ${o.impact.overtime_hours_added ? 'text-rose-600' : ''}`}>{o.impact.overtime_hours_added}h</td>
      <td className="text-right px-2 tabular-nums"><Why text={whyFairness(o.fairness)}><span>{o.fairness.fairness_score}</span></Why></td>
      <td className={`text-right px-2 tabular-nums ${o.impact.unfilled_shifts ? 'text-rose-600 font-semibold' : ''}`}>{o.impact.unfilled_shifts}</td>
      <td className="px-4 text-right"><span className="text-[11px] text-slate-500">{active ? 'Viewing' : 'View'}</span></td>
    </tr>
  );
}

function Metric({ label, value, tone, why }: { label: string; value: React.ReactNode; tone?: string; why?: string }) {
  const c = tone === 'healthy' ? 'text-emerald-700' : tone === 'warning' ? 'text-amber-700' : tone === 'critical' ? 'text-rose-600' : 'text-slate-900';
  return (
    <div className="rounded bg-slate-50 p-2">
      <p className="text-[11px] text-slate-500"><Why text={why}><span>{label}</span></Why></p>
      <p className={`text-sm font-semibold tabular-nums ${c}`}>{value}</p>
    </div>
  );
}

function CompareModal({ open, onClose, p, onPick }: { open: boolean; onClose: () => void; p: Proposal; onPick: (id: string) => void }) {
  const opts = p.result.options;
  const rows: { label: string; get: (o: RepairOption) => number; unit?: string; better: 'low' | 'high' }[] = [
    { label: 'Scheduling impact', get: (o) => o.impact.impact_score, unit: '%', better: 'low' },
    { label: 'Assignments changed', get: (o) => o.impact.assignments_changed, better: 'low' },
    { label: 'People affected', get: (o) => o.impact.employees_affected, better: 'low' },
    { label: 'Overtime added', get: (o) => o.impact.overtime_hours_added, unit: 'h', better: 'low' },
    { label: 'Fairness', get: (o) => o.fairness.fairness_score, better: 'high' },
    { label: 'Uncovered', get: (o) => o.impact.unfilled_shifts, better: 'low' },
  ];
  return (
    <Modal isOpen={open} onClose={onClose} maxWidth="4xl" title="Compare repair options" subtitle="Best value in each row is highlighted">
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead><tr><th />{opts.map((o) => <th key={o.option_id} className="text-left font-semibold px-3 py-2">{o.label}<br /><span className="font-normal text-slate-500">{o.title}</span></th>)}</tr></thead>
          <tbody>
            {rows.map((row) => {
              const vals = opts.map(row.get);
              const best = row.better === 'low' ? Math.min(...vals) : Math.max(...vals);
              return (
                <tr key={row.label} className="border-t border-slate-100">
                  <td className="py-2 pr-3 text-slate-500">{row.label}</td>
                  {opts.map((o, i) => <td key={o.option_id} className={`px-3 tabular-nums ${vals[i] === best ? 'text-emerald-700 font-semibold' : ''}`}>{vals[i]}{row.unit ?? ''}</td>)}
                </tr>
              );
            })}
            <tr className="border-t border-slate-100 align-top">
              <td className="py-2 pr-3 text-slate-500">Changes</td>
              {opts.map((o) => <td key={o.option_id} className="px-3 py-2 space-y-1">{o.changes.map((c) => (
                <p key={c.shift_id}>{c.assignment}: <span className="line-through text-slate-400">{c.from_employee_name ?? 'open'}</span> → <b>{c.to_employee_name ?? 'uncovered'}</b></p>))}</td>)}
            </tr>
            <tr><td />{opts.map((o) => <td key={o.option_id} className="px-3 py-2"><Button size="sm" onClick={() => onPick(o.option_id)}>View {o.label}</Button></td>)}</tr>
          </tbody>
        </table>
      </div>
    </Modal>
  );
}

function ApproveModal({ open, onClose, option, partial, unresolved, onApprove }: {
  open: boolean; onClose: () => void; option?: RepairOption; partial: boolean; unresolved: string[];
  onApprove: (notes: string, allowPartial: boolean) => Promise<void>;
}) {
  const [notes, setNotes] = useState('');
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) { setNotes(''); setAck(false); } }, [open]);
  if (!option) return null;
  return (
    <Modal isOpen={open} onClose={onClose} title={partial ? `Override: publish partial option ${letter(option.label)}?` : `Approve option ${letter(option.label)}: ${option.title}?`}
           subtitle="This publishes a new schedule and notifies only the people whose shifts change."
           footer={<><Button onClick={onClose}>Cancel</Button>
             <Button variant="primary" disabled={busy || (partial && (!ack || !notes.trim()))} onClick={async () => { setBusy(true); await onApprove(notes, partial); setBusy(false); }}>
               {busy ? 'Publishing…' : partial ? 'Publish with uncovered shift' : 'Approve and publish'}</Button></>}>
      <div className="space-y-3 text-xs">
        <ul className="space-y-1">
          {option.changes.map((c) => <li key={c.shift_id}>{fmtDay(c.date)} {c.start} · {c.assignment}: {c.from_employee_name ?? 'Open'} → <b>{c.to_employee_name ?? 'uncovered'}</b></li>)}
        </ul>
        <p className="text-slate-600">{option.impact.employees_affected} {option.impact.employees_affected === 1 ? 'person' : 'people'} will be notified. {option.impact.overtime_hours_added}h overtime.</p>
        {partial && (
          <div className="rounded border border-rose-200 bg-rose-50 p-2.5 text-rose-800 space-y-2">
            {unresolved.map((u) => <p key={u}>{u}</p>)}
            <label className="flex items-start gap-2">
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="mt-0.5" />
              <span>I understand {option.impact.unfilled_shifts} shift(s) stay uncovered. No hard rule is relaxed; I'll arrange cover manually.</span>
            </label>
          </div>
        )}
        <label className="block text-slate-600">{partial ? 'Reason for the override (required, kept in the audit log)' : 'Notes for the audit log (optional)'}
          <input className="input w-full mt-1" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>
      </div>
    </Modal>
  );
}
