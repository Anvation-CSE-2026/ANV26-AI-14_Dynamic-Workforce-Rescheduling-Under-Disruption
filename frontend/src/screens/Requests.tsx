// Employee requests, manager side. Reads the same request records the employee dashboard shows (one
// source of truth) and refreshes on a short poll, so a request filed by an employee appears here within seconds.
import React, { useMemo, useState } from 'react';
import { Check, Clock, MessageSquare, RotateCcw, X } from '../components/common/icons';
import { api, errorMessage } from '../api/client';
import type { EmployeeRequest, RequestStatus } from '../api/types';
import { Button } from '../components/common/Button';
import { Card } from '../components/common/Card';
import { Modal } from '../components/common/Modal';
import { Tabs } from '../components/common/Tabs';
import { EmptyState, ErrorState, Spinner, useAsync, usePoll } from '../components/common/States';
import { useDomain } from '../lib/domain';
import { fmtDay, fmtWhen } from '../lib/format';
import { useToast } from '../lib/toast';
import { REQUEST_KIND } from './Dashboard';

export const STATUS_STYLE: Record<RequestStatus, { label: string; cls: string }> = {
  pending: { label: 'Pending', cls: 'bg-amber-50 text-amber-800 border-amber-200' },
  needs_review: { label: 'Needs review', cls: 'bg-violet-50 text-violet-800 border-violet-200' },
  approved: { label: 'Approved', cls: 'bg-sky-50 text-sky-800 border-sky-200' },
  rejected: { label: 'Declined', cls: 'bg-slate-100 text-slate-600 border-slate-200' },
  completed: { label: 'Completed', cls: 'bg-emerald-50 text-emerald-800 border-emerald-200' },
};

export function StatusPill({ status }: { status: RequestStatus }) {
  const s = STATUS_STYLE[status] ?? STATUS_STYLE.pending;
  return <span className={`inline-flex items-center px-2 py-0.5 rounded-full border text-[11px] font-medium ${s.cls}`}>{s.label}</span>;
}

type Filter = 'open' | 'all' | 'done';

export function Requests({ refreshKey, onChanged, onRepair }: { refreshKey: number; onChanged: () => void; onRepair: () => void }) {
  const { t } = useDomain();
  const toast = useToast();
  const { loading, error, data, reload } = useAsync<EmployeeRequest[]>(() => api.availabilityRequests(), [refreshKey]);
  usePoll(reload, 8000);
  const [filter, setFilter] = useState<Filter>('open');
  const [decide, setDecide] = useState<{ req: EmployeeRequest; status: 'approved' | 'rejected' | 'needs_review' } | null>(null);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  const rows = useMemo(() => (data ?? []).filter((r) =>
    filter === 'all' ? true : filter === 'open' ? ['pending', 'needs_review'].includes(r.status) : ['approved', 'rejected', 'completed'].includes(r.status)), [data, filter]);
  const openCount = (data ?? []).filter((r) => ['pending', 'needs_review'].includes(r.status)).length;

  if (loading && !data) return <Spinner />;
  if (error) return <ErrorState message={error} onRetry={reload} />;

  async function submit() {
    if (!decide) return;
    setBusy(true);
    try {
      await api.decideRequest(decide.req.id, decide.status, note);
      const verb = { approved: 'approved', rejected: 'declined', needs_review: 'marked for review' }[decide.status];
      toast(`${decide.req.employee_name}'s request ${verb}. They can see it now.`);
      if (decide.status === 'approved' && (decide.req.affected_shifts?.length ?? 0) > 0) toast('Their shifts are now an open disruption. Generate a repair from the command center.', 'info');
      setDecide(null);
      setNote('');
      reload();
      onChanged();
    } catch (e) {
      toast(errorMessage(e), 'error');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Employee requests</h2>
          <p className="text-xs text-slate-500">Submitted from the {t('employee', 'employee').toLowerCase()} dashboard. Decisions show up there immediately.</p>
        </div>
        <Tabs activeId={filter} onChange={setFilter} items={[
          { id: 'open', label: 'Needs a decision', badge: openCount }, { id: 'done', label: 'Decided' }, { id: 'all', label: 'All' }]} />
      </div>
      <Card>
        {rows.length === 0 ? <EmptyState title={filter === 'open' ? 'Nothing waiting for a decision' : 'No requests yet'}
                                          hint="Requests appear here as soon as someone submits one." /> : (
          <ul className="divide-y divide-slate-100">
            {rows.map((r) => (
              <li key={r.id} className="px-4 py-3 grid md:grid-cols-[1fr_auto] gap-3 text-xs">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-semibold text-slate-900">{r.employee_name}</span>
                    <StatusPill status={r.status} />
                    <span className="text-slate-600">{REQUEST_KIND[r.kind] ?? r.kind}</span>
                  </div>
                  <p className="text-slate-700 mt-0.5">
                    {fmtDay(r.date)}{r.start ? `, ${r.start}–${r.end}` : ', whole day'}
                    {(r.affected_shifts?.length ?? 0) > 0 ? ` · ${r.affected_shifts!.length} scheduled ${t('shift', 'shift').toLowerCase()}(s) affected` : ' · no scheduled work affected'}
                  </p>
                  {r.reason && <p className="text-slate-500 mt-0.5 flex gap-1"><MessageSquare className="w-3 h-3 mt-0.5 shrink-0" />{r.reason}</p>}
                  {r.manager_note && <p className="text-slate-500 mt-0.5">Admin note: {r.manager_note}</p>}
                  <p className="text-[11px] text-slate-400 mt-1">Submitted {fmtWhen(r.created_at)}{r.decided_by ? ` · last decision by ${r.decided_by}` : ''}</p>
                </div>
                <div className="flex items-start gap-1.5 flex-wrap">
                  {['pending', 'needs_review'].includes(r.status) ? <>
                    {r.status === 'pending' && <Button size="sm" variant="ghost" icon={<RotateCcw className="w-3.5 h-3.5" />} onClick={() => setDecide({ req: r, status: 'needs_review' })}>Needs review</Button>}
                    <Button size="sm" variant="destructive" icon={<X className="w-3.5 h-3.5" />} onClick={() => setDecide({ req: r, status: 'rejected' })}>Decline</Button>
                    <Button size="sm" variant="primary" icon={<Check className="w-3.5 h-3.5" />} onClick={() => setDecide({ req: r, status: 'approved' })}>Approve</Button>
                  </> : r.status === 'approved' && r.disruption_id ? (
                    <Button size="sm" icon={<Clock className="w-3.5 h-3.5" />} onClick={onRepair}>Awaiting repair</Button>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Modal isOpen={!!decide} onClose={() => setDecide(null)}
             title={decide ? `${{ approved: 'Approve', rejected: 'Decline', needs_review: 'Mark for review' }[decide.status]} ${decide.req.employee_name}'s request?` : ''}
             subtitle={decide?.status === 'approved' && (decide.req.affected_shifts?.length ?? 0) > 0
               ? 'Their affected shifts become an open disruption; you then approve a repair as usual.' : 'The employee sees the decision and your note.'}
             footer={<><Button onClick={() => setDecide(null)}>Cancel</Button>
               <Button variant={decide?.status === 'rejected' ? 'destructive' : 'primary'} disabled={busy} onClick={submit}>{busy ? 'Saving…' : 'Confirm'}</Button></>}>
        <label className="block text-xs text-slate-600">Note to the employee {decide?.status === 'approved' ? '(optional)' : '(recommended)'}
          <input className="input w-full mt-1" value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
      </Modal>
    </div>
  );
}
