// Published schedules (each approval publishes one), notifications sent, and the full audit trail.
import React, { useState } from 'react';
import { GitCommit, Bell, CheckCircle2, Clock } from '../components/common/icons';
import { api } from '../api/client';
import type { AuditEvent, Notification, Version } from '../api/types';
import { Card, CardHeader } from '../components/common/Card';
import { Tabs } from '../components/common/Tabs';
import { EmptyState, ErrorState, Spinner, useAsync } from '../components/common/States';
import { fmtDay, fmtWhen, titleCase } from '../lib/format';

export function Versions({ refreshKey }: { refreshKey: number }) {
  const [tab, setTab] = useState<'versions' | 'notifications' | 'audit'>('versions');
  const v = useAsync<Version[]>(() => api.versions(), [refreshKey]);
  const n = useAsync<Notification[]>(() => api.notifications(), [refreshKey]);
  const a = useAsync<AuditEvent[]>(() => api.audit(), [refreshKey]);
  const cur = { versions: v, notifications: n, audit: a }[tab];

  return (
    <div className="space-y-4">
      <Tabs activeId={tab} onChange={setTab} items={[
        { id: 'versions', label: 'Schedules', badge: v.data?.length },
        { id: 'notifications', label: 'Notifications', badge: n.data?.length },
        { id: 'audit', label: 'Audit trail', badge: a.data?.length },
      ]} />
      {cur.loading && !cur.data ? <Spinner /> : cur.error ? <ErrorState message={cur.error} onRetry={cur.reload} /> : (
        <Card>
          {tab === 'versions' && (
            <>
              <CardHeader title="Published schedules" subtitle="Newest first. Only an approved repair publishes a new schedule." />
              {(v.data ?? []).length === 0 ? <EmptyState title="Only the original schedule so far" /> : (
                <ol className="divide-y divide-slate-100 text-xs">
                  {[...(v.data ?? [])].reverse().map((x) => (
                    <li key={x.id} className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <GitCommit className="w-4 h-4 text-slate-400" />
                        <span className="font-semibold">{x.tag}</span>
                        <span className={`text-[10px] px-1.5 rounded ${x.status === 'active' ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-100 text-slate-500'}`}>{x.status}</span>
                        <span className="text-slate-700">{x.title}</span>
                        <span className="ml-auto text-slate-500">{x.created_by} · {fmtWhen(x.created_at)}</span>
                      </div>
                      {x.changes.length > 0 && (
                        <ul className="mt-2 ml-6 space-y-0.5 text-slate-600">
                          {x.changes.map((c) => <li key={c.shift_id}>{fmtDay(c.date)} {c.start} · {c.assignment}: <span className="line-through">{c.from_employee_name ?? 'open'}</span> → <b className="text-slate-900">{c.to_employee_name ?? 'uncovered'}</b></li>)}
                        </ul>
                      )}
                      {x.impact && <p className="mt-1 ml-6 text-slate-500">Impact {x.impact.impact_score}% · {x.impact.employees_affected} affected · fairness {x.fairness?.fairness_score}{x.notes ? ` · “${x.notes}”` : ''}</p>}
                    </li>
                  ))}
                </ol>
              )}
            </>
          )}
          {tab === 'notifications' && (
            <>
              <CardHeader title="Employee notifications" subtitle="Sent only to people whose shifts changed" />
              {(n.data ?? []).length === 0 ? <EmptyState title="No notifications sent yet" /> : (
                <ul className="divide-y divide-slate-100 text-xs">
                  {[...(n.data ?? [])].reverse().map((x) => (
                    <li key={x.id} className="px-4 py-2.5 flex items-start gap-2">
                      <Bell className="w-3.5 h-3.5 text-slate-400 mt-0.5" />
                      <div className="flex-1"><p className="font-medium">{x.employee_name ?? x.employee_id} · {x.title}</p><p className="text-slate-600">{x.body}</p></div>
                      {x.acknowledged_at ? <span className="text-emerald-700 flex items-center gap-1 shrink-0"><CheckCircle2 className="w-3.5 h-3.5" />Acknowledged</span>
                                         : <span className="text-amber-700 flex items-center gap-1 shrink-0"><Clock className="w-3.5 h-3.5" />Awaiting</span>}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
          {tab === 'audit' && (
            <>
              <CardHeader title="Audit trail" subtitle="Every disruption, repair, what-if, approval and acknowledgement" />
              <ul className="divide-y divide-slate-100 text-xs max-h-[70vh] overflow-auto">
                {(a.data ?? []).map((x) => (
                  <li key={x.id} className="px-4 py-2 grid grid-cols-[9rem_10rem_1fr] gap-3">
                    <span className="text-slate-500 tabular-nums">{fmtWhen(x.timestamp)}</span>
                    <span className="font-mono text-[10px] text-slate-600 truncate">{titleCase(x.event_type.toLowerCase())}</span>
                    <span className="text-slate-700"><b className="font-medium">{x.actor}</b>: {x.description}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </Card>
      )}
    </div>
  );
}
