// AI Conflict Resolution Assistant: every conflict explained, with a hard-constraint-checked recommendation.
import { useState } from 'react';
import { api, errorMessage } from '../api/client';
import type { AssistantConflict, StaffingGap } from '../api/types';
import { Button } from '../components/common/Button';
import { Card, CardBody } from '../components/common/Card';
import { EmptyState, ErrorState, Spinner, useAsync, usePoll } from '../components/common/States';
import { CheckRow, Chip, Notice, PageHeader } from '../components/common/ui';
import { AlertTriangle, Sparkles, Users, Wrench } from '../components/common/icons';
import { fmtDay, fmtRange } from '../lib/format';
import { useToast } from '../lib/toast';

const SEV: Record<AssistantConflict['severity'], string> = {
  critical: 'border-l-rose-500', high: 'border-l-orange-500', medium: 'border-l-amber-400', low: 'border-l-slate-300',
};
const SEV_CHIP: Record<AssistantConflict['severity'], 'red' | 'amber' | 'slate'> = { critical: 'red', high: 'amber', medium: 'amber', low: 'slate' };

export function Conflicts({ refreshKey, onRepair, onWorkforce, onChanged }: {
  refreshKey: number; onRepair: (id?: string) => void; onWorkforce: (gap?: StaffingGap) => void; onChanged: () => void;
}) {
  const toast = useToast();
  const { data, loading, error, reload } = useAsync(() => api.conflictAssistant(), [refreshKey]);
  usePoll(reload, 20000);
  const [busy, setBusy] = useState<string | null>(null);

  async function repair(c: AssistantConflict) {
    setBusy(c.id);
    try {
      const p = c.conflict_id ? await api.resolveConflicts([c.conflict_id])
        : await api.reschedule(c.disruption_id ? [c.disruption_id] : undefined);
      onChanged();
      onRepair(p.id);
    } catch (e) { toast(errorMessage(e, 'Unable to generate a repair right now.'), 'error'); } finally { setBusy(null); }
  }

  if (loading && !data) return <Spinner label="Analysing conflicts…" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  const items = data?.conflicts ?? [];
  return (
    <div className="space-y-4">
      <PageHeader title="AI Conflict Resolution Assistant"
                  subtitle="Each conflict is explained from the schedule data. Every suggested person has already passed every hard constraint; the optimizer confirms the final repair when you generate it."
                  actions={<Chip tone={data?.llm ? 'violet' : 'slate'}><Sparkles className="w-3 h-3" />{data?.llm ? `Wording: ${data.llm}` : 'Template explanations (no LLM key)'}</Chip>} />
      {data && data.critical > 0 && <Notice tone="error">{data.critical} critical conflict{data.critical > 1 ? 's' : ''} need attention now.</Notice>}
      {!items.length && <Card><EmptyState title="No conflicts right now" hint="Absences, double bookings, rule violations and staffing gaps appear here as soon as they happen." /></Card>}
      {items.map((c) => (
        <Card key={c.id} className={`border-l-4 ${SEV[c.severity]}`}>
          <CardBody className="p-4 space-y-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Chip tone={SEV_CHIP[c.severity]}><AlertTriangle className="w-3 h-3" />{c.severity.toUpperCase()}</Chip>
                  <span className="text-sm font-semibold text-slate-900">{c.type_label}{c.employee_name ? `: ${c.employee_name}` : ''}</span>
                </div>
                <p className="text-xs text-slate-500 mt-1">{c.task} · {fmtDay(c.date)} {fmtRange(c.start, c.end)} · starts in {Math.max(0, Math.round(c.impact.starts_in_hours))} h · {c.impact.hours} h of work</p>
              </div>
              <div className="flex flex-wrap gap-2">
                {c.type === 'staffing_gap'
                  ? <Button size="sm" variant="action" icon={<Users className="w-3.5 h-3.5" />} onClick={() => onWorkforce(c.gap ?? undefined)}>Request additional workforce</Button>
                  : <Button size="sm" variant="action" icon={<Wrench className="w-3.5 h-3.5" />} disabled={busy === c.id} onClick={() => repair(c)}>{busy === c.id ? 'Optimizing…' : 'Generate optimized repair'}</Button>}
              </div>
            </div>
            <div className="grid md:grid-cols-2 gap-3">
              <div className="space-y-2 min-w-0">
                <p className="text-xs text-slate-700"><span className="font-semibold">Why: </span>{c.why}</p>
                <p className="text-xs text-slate-700"><span className="font-semibold">Explanation: </span>{c.explanation}</p>
                <div className="flex flex-wrap gap-1">{c.constraints.map((k) => <Chip key={k}>{k}</Chip>)}</div>
                {c.policy && <p className="text-[11px] text-slate-500 border-l-2 border-slate-200 pl-2">Policy · {c.policy.citation}: “{c.policy.text.slice(0, 220)}{c.policy.text.length > 220 ? '…' : ''}”</p>}
                <p className="text-[11px] text-slate-400">Explained by {c.explained_by}</p>
                {c.ai_discarded.length > 0 && <Notice tone="warning">AI also suggested {c.ai_discarded.join(', ')}, but they fail a hard constraint, so they were discarded.</Notice>}
              </div>
              <div className="rounded-md bg-slate-50 border border-slate-100 p-3 space-y-2 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs font-semibold text-slate-900">Recommendation</p>
                  <Chip tone={c.confidence === 'high' ? 'green' : c.confidence === 'medium' ? 'amber' : 'red'}>Confidence: {c.confidence}</Chip>
                </div>
                <p className="text-sm font-medium text-slate-900">{c.recommendation}</p>
                {c.recommended && <ul className="space-y-1">{c.recommended.checks.map((k) => <CheckRow key={k.label} ok label={k.label} detail={k.status} warn={k.status === 'FAIR'} />)}</ul>}
                <p className="text-[11px] text-slate-500">{c.eligible_count} eligible after hard constraints · funnel: {c.funnel.map((f) => `${f.stage} ${f.remaining}`).join(' → ')}</p>
                <div>
                  <p className="text-[11px] font-semibold text-slate-600 uppercase tracking-wide mt-2">Alternatives</p>
                  <ul className="mt-1 space-y-1 text-xs text-slate-700">
                    {c.alternatives.map((a, i) => (
                      <li key={i}>• {a.kind === 'employee' ? <>{a.employee_name} <span className="text-slate-500">(rank {a.rank}: {a.tradeoffs.join(', ')})</span></> : a.label}</li>
                    ))}
                  </ul>
                </div>
                {c.rejected.length > 0 && <p className="text-[11px] text-slate-500">Ruled out: {c.rejected.map((r) => `${r.employee_name} (${r.reason.toLowerCase()})`).join(', ')}</p>}
              </div>
            </div>
            {c.strategies.length > 0 && (
              <div className="text-xs text-slate-700"><span className="font-semibold">Strategies: </span>{c.strategies.join(' · ')}</div>
            )}
          </CardBody>
        </Card>
      ))}
      <p className="text-[11px] text-slate-400">{data?.note}</p>
    </div>
  );
}
