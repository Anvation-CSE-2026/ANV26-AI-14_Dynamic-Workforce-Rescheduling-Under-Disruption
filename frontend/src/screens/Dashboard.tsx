import React, { useState } from 'react';
import { AlertTriangle, Sparkles, Zap, Send, CheckCircle2, Users, Clock, ShieldCheck, Scale, Activity } from '../components/common/icons';
import { api, errorMessage } from '../api/client';
import { Overview, type OverviewTarget } from '../components/widgets/Overview';
import type { Dashboard as DashboardData, Employee, Interpretation, WorkspaceSummary } from '../api/types';
import { Button } from '../components/common/Button';
import { Card, CardBody, CardHeader } from '../components/common/Card';
import { MetricCard } from '../components/common/MetricCard';
import { StatusIndicator } from '../components/common/Badge';
import { ErrorState, Spinner, useAsync, usePoll } from '../components/common/States';
import { Why } from '../components/common/Why';
import { whyFairness, whyImpact } from '../components/repair/reasons';
import { WIDGETS } from '../components/widgets/Widgets';
import { useDomain } from '../lib/domain';
import { fmtDay, fmtKpi, impactTone, kpiTone } from '../lib/format';
import { useToast } from '../lib/toast';

export const REQUEST_KIND: Record<string, string> = {
  unavailable: "Can't work", time_off: 'Time off', shift_swap: 'Shift swap', preference: 'Preference',
};

export function Dashboard({ workspace, onRepair, refreshKey, onChanged, onRequests, onNavigate }: {
  onNavigate?: (t: OverviewTarget) => void;
  workspace: WorkspaceSummary;
  onRepair: (proposalId?: string) => void;
  refreshKey: number;
  onChanged: () => void;
  onRequests: () => void;
}) {
  const { config, t } = useDomain();
  const toast = useToast();
  const { loading, error, data, reload } = useAsync<DashboardData>(() => api.dashboard(), [refreshKey]);
  usePoll(reload, 12000);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [interp, setInterp] = useState<Interpretation | null>(null);
  const people = useAsync<Employee[]>(() => api.employees(), [workspace.org]);
  const sampleName = (people.data?.find((e) => e.id === workspace.presets[0]?.employee_id)?.name ?? people.data?.[0]?.name ?? 'Rahul').split(' ')[0];

  if (loading && !data) return <Spinner />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;

  async function simulate(presetId: string, label?: string | null) {
    setBusy(presetId);
    try {
      await api.reportDisruption({ preset_id: presetId });
      toast(`Simulated: ${label}. Generating repair options…`, 'info');
      const p = await api.reschedule();
      toast('Repair generated successfully.');
      onChanged();
      onRepair(p.id);
    } catch (e) {
      toast(errorMessage(e), 'error');
    } finally {
      setBusy(null);
    }
  }

  async function ask(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy('ask');
    setInterp(null);
    try {
      const r = await api.interpret(text);
      const intent = r.intent.intent;
      if (intent === 'report_disruption') {
        const res = r.result ?? {};
        if (res.status !== 'READY') {
          setInterp(res.interpretation ?? null);
          toast('ResQWork needs a bit more information.', 'warning');
        } else {
          setInterp(res.interpretation ?? null);
          toast(`Understood: ${res.interpretation?.confirmation_summary ?? 'disruption recorded'}`, 'info');
          const p = await api.reschedule((res.disruptions ?? []).map((d) => d.id));
          onChanged();
          onRepair(p.id);
        }
      } else if (intent === 'what_if') {
        toast(r.result?.scenario?.summary ?? 'What-if ran.', 'info');
        onChanged();
        if (r.result?.proposal) onRepair(r.result.proposal.id);
      } else if (intent === 'manager_feedback') {
        toast(r.result?.status === 'READY' ? `Saved: ${r.result.summary}` : 'Feedback not actionable.', r.result?.status === 'READY' ? 'success' : 'warning');
      } else if (intent === 'policy_question') {
        const hit = r.result?.hits?.[0];
        toast(hit ? `${hit.citation}: ${hit.text}` : 'No applicable policy found.', 'info');
      } else {
        toast(r.message ?? 'Try describing a disruption.', 'info');
      }
      setText('');
    } catch (err) {
      toast(errorMessage(err), 'error');
    } finally {
      setBusy(null);
    }
  }

  const lp = data.latest_proposal;
  const rec = lp?.recommended;
  const m = data.metrics;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">{data.dashboardName}</h2>
          <p className="text-xs text-slate-500">{data.organization.name}{data.organization.location ? `, ${data.organization.location}` : ''}. Current schedule: {data.version}</p>
        </div>
        <StatusIndicator status={data.open_disruptions.length ? 'critical' : 'healthy'}
                         label={data.open_disruptions.length ? `${data.open_disruptions.length} open disruption${data.open_disruptions.length > 1 ? 's' : ''}` : 'Schedule healthy'} />
      </div>

      {data.overview && <Overview o={data.overview} onNavigate={onNavigate} />}

      <section aria-label="Key indicators" className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3">
        {data.kpis.map((k) => {
          const f = fmtKpi(k, k.value);
          const tone = kpiTone(k, k.value);
          return <MetricCard key={k.id} label={k.label} value={f.value} unit={f.unit} subtext={k.hint}
                             badge={<span className={`w-2 h-2 rounded-full ${tone === 'healthy' ? 'bg-emerald-500' : tone === 'warning' ? 'bg-amber-500' : tone === 'critical' ? 'bg-rose-500' : 'bg-slate-300'}`} />} />;
        })}
      </section>

      <section aria-label="Workforce status" className="flex flex-wrap gap-2 text-[11px]">
        {data.commonKpis.map((k) => {
          const f = fmtKpi(k, k.value);
          return <span key={k.id} className="px-2.5 py-1 rounded border border-slate-200 bg-white text-slate-600" title={k.hint}>{k.label}: <b className="text-slate-900">{f.value}{f.unit && ` ${f.unit}`}</b></span>;
        })}
      </section>

      <div className="grid grid-cols-1 xl:grid-cols-[1.25fr_1fr] gap-5 [&>*]:min-w-0">
        <Card>
          <CardHeader title="Disruption center" subtitle="Report in plain language or simulate a scenario" />
          <CardBody className="p-4 space-y-4">
            <form onSubmit={ask} className="flex flex-col sm:flex-row gap-2">
              <label htmlFor="ask" className="sr-only">Describe a disruption, ask a what-if, give feedback or ask about a policy</label>
              <input id="ask" value={text} onChange={(e) => setText(e.target.value)} className="input flex-1 min-w-0"
                     placeholder={`e.g. "${sampleName} is sick tomorrow, no overtime"`} />
              <Button type="submit" variant="primary" icon={<Send className="w-3.5 h-3.5" />} disabled={busy === 'ask'}>{busy === 'ask' ? 'Thinking…' : 'Ask ResQWork'}</Button>
            </form>
            {interp && interp.status !== 'READY' && (
              <div className="rounded border border-amber-200 bg-amber-50 p-3 text-xs space-y-1" role="alert">
                {interp.issues.map((i, n) => (
                  <p key={n} className="text-amber-900">{i.message}{i.candidates.length > 0 && <> · {i.candidates.map((c) => c.name).join(' / ')}</>}</p>
                ))}
              </div>
            )}
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-2">Demo mode: simulate</p>
              <div className="flex flex-wrap gap-2">
                {workspace.presets.map((p) => (
                  <Button key={p.id} size="md" variant={p.severity === 'critical' ? 'action' : 'secondary'} icon={<Zap className="w-3.5 h-3.5" />}
                          disabled={!!busy} onClick={() => simulate(p.id, p.label)}>
                    {busy === p.id ? 'Repairing…' : `Simulate ${p.label}`}
                  </Button>
                ))}
              </div>
            </div>
            {data.conflicts.length > 0 && (
              <div className="border border-amber-300 rounded bg-amber-50/60 p-3 text-xs space-y-2" role="alert">
                <div className="flex items-start gap-2">
                  <AlertTriangle className="w-4 h-4 text-amber-600 mt-0.5 shrink-0" />
                  <div className="flex-1">
                    <p className="font-medium text-slate-900">{data.conflicts.length} schedule conflict{data.conflicts.length > 1 ? 's' : ''} in the current schedule</p>
                    <ul className="mt-1 space-y-0.5 text-slate-700">
                      {data.conflicts.slice(0, 4).map((c) => (
                        <li key={c.id}><Why text={`Breaks the hard constraint "${c.hard_constraint}". ${Object.values(c.release)[0] ? `Repair takes the assignee off the conflicting shift (${Object.values(c.release)[0]}) and finds valid cover.` : 'Repair finds valid cover for the open shift.'}`}>
                          <span className="font-medium">{c.label}</span></Why>: {c.message}</li>
                      ))}
                    </ul>
                  </div>
                  <Button size="sm" variant="action" disabled={!!busy} onClick={async () => {
                    setBusy('conflicts');
                    try { const p = await api.resolveConflicts(); onChanged(); onRepair(p.id); }
                    catch (e) { toast(errorMessage(e), 'error'); } finally { setBusy(null); }
                  }}>{busy === 'conflicts' ? 'Solving…' : 'Repair conflicts'}</Button>
                </div>
              </div>
            )}
            {data.open_disruptions.length > 0 && (
              <div className="border border-rose-200 rounded divide-y divide-rose-100">
                {data.open_disruptions.map((d) => (
                  <div key={d.id} className="p-3 text-xs flex items-start gap-3 bg-rose-50/50">
                    <AlertTriangle className="w-4 h-4 text-rose-500 mt-0.5 shrink-0" />
                    <div className="flex-1">
                      {d.disruption ? <>
                        <p className="font-medium text-slate-900">{d.employee_name} unavailable · {fmtDay(d.disruption.date)}{d.disruption.start ? ` ${d.disruption.start}–${d.disruption.end}` : ' (all day)'}</p>
                        <p className="text-slate-600">{d.affected_shifts.length} {t('shift', 'shift').toLowerCase()}(s) affected · severity {d.disruption.severity} · {d.source}</p>
                      </> : <>
                        <p className="font-medium text-slate-900">Schedule conflicts being repaired</p>
                        <p className="text-slate-600">{(d.conflicts ?? []).map((c) => c.label).join(', ')}</p>
                      </>}
                    </div>
                    <Button size="sm" variant="action" onClick={async () => { setBusy(d.id); try { const p = await api.reschedule([d.id]); onChanged(); onRepair(p.id); } catch (e) { toast(errorMessage(e), 'error'); } finally { setBusy(null); } }}>
                      {busy === d.id ? 'Solving…' : 'Generate repair'}
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="AI repair recommendation" subtitle={lp ? (lp.problem?.join('; ') || `${lp.options} option(s)`) : 'No repair generated yet'}
                      action={lp && <Button size="sm" variant="primary" onClick={() => onRepair(lp.id)}>Open repair centre</Button>} />
          <CardBody className="p-4">
            {lp && !lp.feasible ? (
              <div className="space-y-2 text-xs" role="alert">
                <p className="text-sm font-semibold text-rose-700 flex items-center gap-1.5"><AlertTriangle className="w-4 h-4" />No feasible repair exists</p>
                {lp.unresolved.map((u, i) => <p key={i} className="text-slate-700">{u.summary}</p>)}
                <p className="text-slate-500">Nothing was assigned illegally. Open the repair centre for the constraint analysis and possible resolutions.</p>
              </div>
            ) : rec ? (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Sparkles className="w-4 h-4 text-[var(--accent)]" />
                  <span className="text-sm font-semibold">{rec.label}: {rec.title}</span>
                  <StatusIndicator status={impactTone(rec.impact.impact_level)} label={`Impact ${rec.impact.impact_level}`} size="sm" />
                </div>
                <dl className="grid grid-cols-2 gap-2 text-xs">
                  <Stat icon={<Users className="w-3.5 h-3.5" />} label="Employees affected" value={rec.impact.employees_affected} />
                  <Stat icon={<Activity className="w-3.5 h-3.5" />} label="Shifts changed" value={rec.impact.assignments_changed} why={whyImpact(rec.impact)} />
                  <Stat icon={<Clock className="w-3.5 h-3.5" />} label="Overtime" value={`${rec.impact.overtime_hours_added}h`} />
                  <Stat icon={<ShieldCheck className="w-3.5 h-3.5" />} label="Skill coverage" value={`${rec.impact.skill_coverage_pct}%`} />
                  <Stat icon={<Scale className="w-3.5 h-3.5" />} label="Fairness" value={rec.fairness.fairness_score} why={whyFairness(rec.fairness)} />
                  <Stat icon={<Activity className="w-3.5 h-3.5" />} label="Scheduling impact" value={`${rec.impact.impact_score}%`} why={whyImpact(rec.impact)} />
                </dl>
                {lp?.status === 'approved' && <p className="text-xs text-emerald-700 flex items-center gap-1"><CheckCircle2 className="w-3.5 h-3.5" /> Approved and published.</p>}
              </div>
            ) : (
              <p className="text-xs text-slate-500">Simulate a disruption or describe one: ResQWork will generate repair options, explain them, and wait for your approval.</p>
            )}
          </CardBody>
        </Card>
      </div>

      <div className="grid lg:grid-cols-3 gap-5">
        {WIDGETS.department_coverage && <WIDGETS.department_coverage data={data.widgets} />}
        <Card>
          <CardHeader title="Risk indicators" subtitle={config?.label} />
          <CardBody className="p-4 space-y-2 text-xs">
            {config?.riskIndicators.map((r) => (
              <div key={r.id} className="flex justify-between"><span className="text-slate-600">{r.label}</span>
                <b className={(m[r.metric]?.value ?? 0) > 0 ? 'text-rose-600' : 'text-emerald-700'}>{m[r.metric]?.value ?? 0}</b></div>
            ))}
            {(m.fatigue_risk_count?.items?.length ?? 0) > 0 && <p className="text-[11px] text-slate-500 pt-1">At risk: {m.fatigue_risk_count.items!.slice(0, 5).join(', ')}</p>}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Recommended actions" subtitle="For the admin" />
          <CardBody className="p-4">
            <ul className="space-y-2 text-xs text-slate-700">
              {config?.recommendedActions.map((a) => <li key={a} className="flex gap-2"><CheckCircle2 className="w-3.5 h-3.5 text-slate-400 mt-0.5 shrink-0" />{a}</li>)}
            </ul>
            {data.pending_requests.length > 0 && (
              <div className="mt-4 pt-3 border-t border-slate-100">
                <p className="text-xs font-semibold text-slate-700 mb-2">Employee requests waiting for you</p>
                {data.pending_requests.slice(0, 4).map((r) => (
                  <div key={r.id} className="flex items-center justify-between gap-2 text-xs py-1">
                    <span className="min-w-0 truncate">{r.employee_name} · {REQUEST_KIND[r.kind] ?? r.kind} · {fmtDay(r.date)}{r.start ? ` ${r.start}–${r.end}` : ''}
                      {r.status === 'needs_review' && <span className="ml-1 text-amber-700">(review)</span>}</span>
                    <span className="flex gap-1 shrink-0">
                      <Button size="sm" variant="ghost" onClick={async () => { try { await api.decideRequest(r.id, 'rejected'); toast(`${r.employee_name}'s request declined.`, 'info'); onChanged(); reload(); } catch (e) { toast(errorMessage(e), 'error'); } }}>Decline</Button>
                      <Button size="sm" onClick={async () => { try { await api.decideRequest(r.id, 'approved'); toast(`${r.employee_name}'s request approved.`); onChanged(); reload(); } catch (e) { toast(errorMessage(e), 'error'); } }}>Approve</Button>
                    </span>
                  </div>
                ))}
                {data.pending_requests.length > 4 && <button className="text-xs text-[var(--accent)] mt-1" onClick={onRequests}>All {data.pending_requests.length} requests</button>}
              </div>
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

function Stat({ icon, label, value, why }: { icon: React.ReactNode; label: string; value: React.ReactNode; why?: string }) {
  return (
    <div className="flex items-center gap-2 p-2 rounded bg-slate-50">
      <span className="text-slate-400">{icon}</span>
      <dt className="text-slate-500 flex-1"><Why text={why}><span>{label}</span></Why></dt>
      <dd className="font-semibold tabular-nums text-slate-900">{value}</dd>
    </div>
  );
}


