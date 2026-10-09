// Repair Center list: active/critical disruptions and every repair by state. View opens full details;
// Hide moves a repair out of the list (never deletes); "Show hidden" brings hidden repairs back.
import { useState } from 'react';
import { api, errorMessage } from '../api/client';
import type { RepairCenterRow } from '../api/types';
import { Button } from '../components/common/Button';
import { Card } from '../components/common/Card';
import { EmptyState, ErrorState, Spinner, useAsync, usePoll } from '../components/common/States';
import { Tabs } from '../components/common/Tabs';
import { Chip, PageHeader } from '../components/common/ui';
import { CheckCircle2, Eye, EyeOff, Wrench } from '../components/common/icons';
import { fmtWhen } from '../lib/format';
import { useToast } from '../lib/toast';

type State = 'pending' | 'approved' | 'completed' | 'rejected' | 'all';

export function RepairCenter({ refreshKey, onView, onChanged }: { refreshKey: number; onView: (id?: string) => void; onChanged: () => void }) {
  const toast = useToast();
  const [hidden, setHidden] = useState(false);
  const [tab, setTab] = useState<State>('pending');
  const { data, loading, error, reload } = useAsync(() => api.repairCenter(hidden), [refreshKey, hidden]);
  usePoll(reload, 15000);
  const [busy, setBusy] = useState<string | null>(null);

  async function act(id: string, fn: () => Promise<unknown>, ok: string) {
    setBusy(id);
    try { await fn(); toast(ok); reload(); onChanged(); } catch (e) { toast(errorMessage(e), 'error'); } finally { setBusy(null); }
  }
  async function repairOpen(ids?: string[]) {
    setBusy('new');
    try { const p = await api.reschedule(ids); onChanged(); onView(p.id); } catch (e) { toast(errorMessage(e, 'Unable to generate a repair right now.'), 'error'); } finally { setBusy(null); }
  }

  if (loading && !data) return <Spinner />;
  if (error || !data) return <ErrorState message={error ?? 'Unable to load repairs.'} onRetry={reload} />;
  const c = data.counts;
  const rows = data.repairs.filter((r) => tab === 'all' || r.state === tab);
  return (
    <div className="space-y-4">
      <PageHeader title="Repair Center" subtitle="Every disruption and repair in one place. Nothing changes the schedule until an admin approves."
                  actions={<Button size="sm" variant={hidden ? 'primary' : 'secondary'} icon={hidden ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                                   onClick={() => setHidden((h) => !h)}>{hidden ? 'Hide hidden repairs' : `Show hidden (${c.hidden})`}</Button>} />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {[['Active disruptions', c.active_disruptions], ['Critical', c.critical_disruptions], ['Pending repairs', c.pending], ['Completed', c.completed]].map(([l, v]) => (
          <div key={String(l)} className="bg-white border border-slate-200 rounded-lg p-3"><p className="text-[11px] uppercase tracking-wide text-slate-500">{l}</p><p className="text-xl font-bold">{v}</p></div>
        ))}
      </div>
      {data.active_disruptions.length > 0 && (
        <Card className="p-3">
          <p className="text-xs font-semibold text-slate-800 mb-2">Active disruptions</p>
          <ul className="space-y-1.5">
            {data.active_disruptions.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 text-xs">
                <span>{data.critical_disruption_ids.includes(d.id) && <Chip tone="red">CRITICAL</Chip>} <b>{d.employee_name}</b>: {d.kind === 'conflict' ? 'schedule conflict' : `${d.disruption?.date} ${d.disruption?.start ?? ''}${d.disruption?.end ? '–' + d.disruption.end : ''}`} · {d.affected_shifts.length} shift(s)</span>
                <Button size="sm" variant="action" icon={<Wrench className="w-3.5 h-3.5" />} disabled={busy === 'new'} onClick={() => repairOpen([d.id])}>Generate repair</Button>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <div className="overflow-x-auto max-w-full"><Tabs<State> items={[{ id: 'pending', label: 'Pending', badge: c.pending }, { id: 'approved', label: 'Approved', badge: c.approved },
        { id: 'completed', label: 'Completed', badge: c.completed }, { id: 'rejected', label: 'Rejected', badge: c.rejected }, { id: 'all', label: 'All' }]}
        activeId={tab} onChange={setTab} /></div>
      <Card>
        {!rows.length ? <EmptyState title="Nothing here" hint={tab === 'pending' ? 'New repairs appear here when a disruption is reported.' : undefined} /> : (
          <ul className="divide-y divide-slate-100">
            {rows.map((r) => <Row key={r.id} r={r} busy={busy === r.id} onView={() => onView(r.id)}
              onHide={() => act(r.id, () => (r.hidden ? api.unhideRepair(r.id) : api.hideRepair(r.id)), r.hidden ? 'Repair restored to the list.' : 'Repair hidden (not deleted).')}
              onComplete={() => act(r.id, () => api.completeRepair(r.id), 'Marked completed. Eligible rewards were granted.')} />)}
          </ul>
        )}
      </Card>
    </div>
  );
}

function Row({ r, busy, onView, onHide, onComplete }: { r: RepairCenterRow; busy: boolean; onView: () => void; onHide: () => void; onComplete: () => void }) {
  const tone = r.state === 'completed' ? 'green' : r.state === 'approved' ? 'blue' : r.state === 'rejected' ? 'slate' : 'amber';
  return (
    <li className={`p-3 flex flex-wrap items-start justify-between gap-3 ${r.hidden ? 'opacity-60' : ''}`}>
      <div className="min-w-0 text-xs">
        <div className="flex flex-wrap items-center gap-1.5">
          <Chip tone={tone}>{r.state}</Chip>
          {r.critical && <Chip tone="red">critical</Chip>}
          {r.what_if && <Chip tone="violet">what-if</Chip>}
          {r.hidden && <Chip>hidden</Chip>}
          <span className="font-semibold text-slate-900 break-words min-w-0">{r.problem.join('; ') || 'Schedule repair'}</span>
        </div>
        <p className="text-slate-500 mt-1">
          {fmtWhen(r.created_at)} · {r.affected_shifts} shift(s) · {r.options} option(s) · {r.solver}
          {r.recommended && <> · {r.recommended.label}: {r.recommended.changes} change(s), {r.recommended.overtime} h overtime, fairness {r.recommended.fairness}</>}
          {r.unresolved > 0 && <span className="text-rose-600"> · {r.unresolved} unresolved</span>}
          {r.pending_completion > 0 && <> · {r.pending_completion} assignment(s) awaiting completion</>}
        </p>
      </div>
      <div className="flex flex-wrap gap-1.5">
        <Button size="sm" icon={<Eye className="w-3.5 h-3.5" />} onClick={onView}>View</Button>
        {r.state === 'approved' && <Button size="sm" icon={<CheckCircle2 className="w-3.5 h-3.5" />} disabled={busy} onClick={onComplete}>Mark completed</Button>}
        <Button size="sm" variant="ghost" icon={r.hidden ? <Eye className="w-3.5 h-3.5" /> : <EyeOff className="w-3.5 h-3.5" />} disabled={busy} onClick={onHide}>{r.hidden ? 'Unhide' : 'Hide'}</Button>
      </div>
    </li>
  );
}
