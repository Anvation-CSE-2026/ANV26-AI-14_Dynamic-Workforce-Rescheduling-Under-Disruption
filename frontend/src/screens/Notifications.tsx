// Notification center (admin): three levels, delivery per channel, escalation of unacknowledged Level 2 notices.
import { useState } from 'react';
import { api, errorMessage } from '../api/client';
import { Button } from '../components/common/Button';
import { Card, CardHeader } from '../components/common/Card';
import { EmptyState, ErrorState, Spinner, useAsync, usePoll } from '../components/common/States';
import { Chip, Field, Notice, PageHeader, SeverityPill } from '../components/common/ui';
import { Bell, Mail, MessageCircle, Phone, Zap } from '../components/common/icons';
import { fmtWhen } from '../lib/format';
import { useToast } from '../lib/toast';

const CH_ICON = { dashboard: Bell, email: Mail, whatsapp: MessageCircle, sms: Phone } as const;

export function Notifications({ refreshKey }: { refreshKey: number }) {
  const toast = useToast();
  const settings = useAsync(() => api.notificationSettings(), [refreshKey]);
  const summary = useAsync(() => api.notificationSummary(), [refreshKey]);
  const rows = useAsync(() => api.notificationAudit(), [refreshKey]);
  usePoll(() => { summary.reload(); rows.reload(); }, 15000);
  const [minutes, setMinutes] = useState<string | null>(null);
  const [level, setLevel] = useState<0 | 1 | 2 | 3>(0);

  async function escalate() {
    try { const r = await api.escalate(false); toast(r.escalated.length ? `${r.escalated.length} notification(s) escalated to WhatsApp + SMS.` : 'Nothing is due for escalation.', 'info'); rows.reload(); summary.reload(); }
    catch (e) { toast(errorMessage(e), 'error'); }
  }
  async function save() {
    try { await api.saveNotificationSettings(Number(minutes)); toast('Escalation window saved.'); setMinutes(null); settings.reload(); }
    catch (e) { toast(errorMessage(e), 'error'); }
  }
  if ((settings.loading && !settings.data) || (summary.loading && !summary.data)) return <Spinner />;
  if (settings.error || summary.error || !settings.data || !summary.data) return <ErrorState message={settings.error ?? summary.error ?? 'Unable to load.'} onRetry={() => { settings.reload(); summary.reload(); }} />;
  const s = summary.data;
  const simulated = Object.entries(s.providers).filter(([, v]) => v === 'simulated').map(([k]) => k);
  const list = (rows.data ?? []).filter((r) => !level || r.severity === level);
  return (
    <div className="space-y-4">
      <PageHeader title="Notifications" subtitle="Level 1 informational (dashboard + email) · Level 2 important (needs acknowledgement; escalates to WhatsApp + SMS) · Level 3 critical (all channels at once)."
                  actions={<Button size="sm" variant="destructive" icon={<Zap className="w-3.5 h-3.5" />} onClick={escalate}>Run escalation now</Button>} />
      <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
        {[['Total', s.total], ['Level 1', s.by_level['1'] ?? 0], ['Level 2', s.by_level['2'] ?? 0], ['Level 3', s.by_level['3'] ?? 0], ['Awaiting ack', s.awaiting_acknowledgement]].map(([l, v]) => (
          <div key={String(l)} className="bg-white border border-slate-200 rounded-lg p-3"><p className="text-[11px] uppercase tracking-wide text-slate-500">{l}</p><p className="text-xl font-bold">{v}</p></div>
        ))}
      </div>
      {simulated.length > 0 && <Notice tone="info">{simulated.join(', ')} are <b>simulated</b>: no provider credentials are configured, so messages are rendered and logged but not sent. Set SMTP_* / TWILIO_* in backend/.env to send for real.</Notice>}
      <Card className="p-4">
        <div className="flex flex-wrap items-end gap-3 text-xs">
          <Field label="Escalate Level 2 if not acknowledged within (minutes)">
            <input className="input w-28" inputMode="numeric" value={minutes ?? String(settings.data.l2_escalation_minutes)} onChange={(e) => setMinutes(e.target.value)} />
          </Field>
          {minutes !== null && <Button size="sm" variant="primary" onClick={save}>Save</Button>}
          <span className="text-slate-500">{s.escalated} escalated · {s.acknowledged} acknowledged · Voice: future extension (not enabled)</span>
        </div>
      </Card>
      <Card>
        <CardHeader title="Delivery log" subtitle="One row per notification and channel"
                    action={<select aria-label="Level" className="input" value={level} onChange={(e) => setLevel(Number(e.target.value) as 0 | 1 | 2 | 3)}>
                      <option value={0}>All levels</option><option value={1}>Level 1</option><option value={2}>Level 2</option><option value={3}>Level 3</option></select>} />
        {rows.loading && !rows.data ? <Spinner /> : !list.length ? <EmptyState title="No notifications yet" /> : (
          <div className="overflow-x-auto max-h-[32rem]">
            <table className="w-full text-xs text-left">
              <thead className="text-[11px] uppercase text-slate-500 bg-slate-50 sticky top-0"><tr>
                <th className="px-3 py-2">Level</th><th className="px-2">Employee</th><th className="px-2">Message</th><th className="px-2">Channel</th><th className="px-2">Status</th><th className="px-2">Sent</th><th className="px-2">Acknowledged</th></tr></thead>
              <tbody>{list.slice(0, 300).map((r, i) => {
                const Icon = CH_ICON[r.channel as keyof typeof CH_ICON] ?? Bell;
                return (
                  <tr key={`${r.notification_id}-${r.channel}-${i}`} className="border-t border-slate-100">
                    <td className="px-3 py-1.5"><SeverityPill level={r.severity} /></td>
                    <td className="px-2">{r.employee_name ?? r.employee_id}</td>
                    <td className="px-2">{r.message}</td>
                    <td className="px-2 whitespace-nowrap"><Icon className="w-3.5 h-3.5 inline mr-1 text-slate-400" />{r.channel}{r.escalation_level ? <Chip tone="amber" className="ml-1">escalated</Chip> : null}</td>
                    <td className="px-2"><Chip tone={r.status === 'delivered' ? 'green' : r.status === 'failed' ? 'red' : 'slate'}>{r.status}{r.provider === 'simulated' ? ' (simulated)' : ''}</Chip></td>
                    <td className="px-2 whitespace-nowrap">{fmtWhen(r.sent_at)}</td>
                    <td className="px-2 whitespace-nowrap">{r.acknowledged_at ? fmtWhen(r.acknowledged_at) : '—'}</td>
                  </tr>);
              })}</tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
