// Profile for Admin and Employee: identity, contact, avatar, notification preferences, password, sessions.
import { useState, type FormEvent } from 'react';
import { api, errorMessage } from '../api/client';
import { Button } from '../components/common/Button';
import { Card, CardBody, CardHeader } from '../components/common/Card';
import { ErrorState, Spinner, useAsync } from '../components/common/States';
import { Avatar, Chip, Field, Notice, PageHeader } from '../components/common/ui';
import { KeyRound, LogOut } from '../components/common/icons';
import { fmtWhen } from '../lib/format';
import { useToast } from '../lib/toast';

export function Profile({ onLogout, onUpdated }: { onLogout: () => void; onUpdated?: () => void }) {
  const toast = useToast();
  const { data, loading, error, reload } = useAsync(() => api.profile(), []);
  const [f, setF] = useState<{ name?: string; phone?: string; prefs?: Record<string, boolean> }>({});
  const [busy, setBusy] = useState(false);
  if (loading && !data) return <Spinner />;
  if (error || !data) return <ErrorState message={error ?? 'Unable to load your profile.'} onRetry={reload} />;
  const u = data.user;
  const e = data.employee;
  const prefs = { email: true, sms: true, whatsapp: true, ...(u.notification_preferences ?? {}), ...(f.prefs ?? {}) };
  const dirty = f.name !== undefined || f.phone !== undefined || f.prefs !== undefined;

  async function save() {
    setBusy(true);
    try {
      await api.updateProfile({ name: f.name, phone: f.phone, notification_preferences: f.prefs ? prefs : undefined });
      toast('Profile saved.'); setF({}); reload(); onUpdated?.();
    } catch (err) { toast(errorMessage(err), 'error'); } finally { setBusy(false); }
  }
  async function avatar(file: File) {
    if (file.size > 280_000) { toast('Choose an image under 280 KB.', 'warning'); return; }
    const url = await new Promise<string>((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result)); r.onerror = () => rej(new Error('read failed')); r.readAsDataURL(file); });
    try { await api.updateProfile({ avatar: url }); toast('Photo updated.'); reload(); onUpdated?.(); } catch (err) { toast(errorMessage(err), 'error'); }
  }
  async function signOut(everywhere: boolean) {
    try { await api.logout(everywhere); } catch { /* already signed out on the server */ }
    onLogout();
  }

  return (
    <div className="space-y-4 max-w-4xl">
      <PageHeader title="Profile" subtitle={data.role_label} />
      <Card>
        <CardBody className="p-4 flex flex-wrap items-center gap-4">
          <Avatar name={u.name} src={u.avatar} size={64} />
          <div className="min-w-0 flex-1">
            <p className="text-base font-semibold text-slate-900">{u.name}</p>
            <p className="text-xs text-slate-500">{u.email} · {data.role_label}{data.organization ? ` · ${data.organization.name}` : ''}</p>
            <p className="text-[11px] text-slate-400 mt-1">Account {u.status ?? 'active'} · created {fmtWhen(u.created_at ?? null)} · last sign-in {fmtWhen(u.last_login ?? null)}</p>
          </div>
          <label className="text-xs font-medium text-[var(--accent)] cursor-pointer hover:underline">Change photo
            <input type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" onChange={(x) => { const file = x.target.files?.[0]; if (file) void avatar(file); }} /></label>
        </CardBody>
      </Card>
      <div className="grid md:grid-cols-2 gap-4">
        <Card>
          <CardHeader title="Contact & preferences" subtitle="You can change these yourself" />
          <CardBody className="p-4 space-y-3">
            <Field label="Full name"><input className="input w-full" value={f.name ?? u.name ?? ''} onChange={(x) => setF({ ...f, name: x.target.value })} /></Field>
            <Field label="Phone" hint="Used for SMS / WhatsApp alerts"><input className="input w-full" value={f.phone ?? u.phone ?? e?.phone ?? ''} onChange={(x) => setF({ ...f, phone: x.target.value })} /></Field>
            <fieldset className="text-xs space-y-1"><legend className="font-medium text-slate-700 mb-1">Notification channels (critical alerts always use every channel)</legend>
              {(['email', 'sms', 'whatsapp'] as const).map((k) => (
                <label key={k} className="flex items-center gap-2"><input type="checkbox" checked={prefs[k] !== false} onChange={(x) => setF({ ...f, prefs: { ...prefs, [k]: x.target.checked } })} />{k === 'sms' ? 'SMS' : k === 'whatsapp' ? 'WhatsApp' : 'Email'}</label>
              ))}
            </fieldset>
            <Button variant="primary" disabled={!dirty || busy} onClick={save}>Save changes</Button>
          </CardBody>
        </Card>
        {e ? (
          <Card>
            <CardHeader title="Work details" subtitle="Managed by your admin" />
            <CardBody className="p-4 text-xs space-y-1.5">
              <p><span className="text-slate-500">Employee ID:</span> {e.id}</p>
              <p><span className="text-slate-500">Department:</span> {e.department ?? '—'} · <span className="text-slate-500">Role:</span> {e.role}</p>
              <p><span className="text-slate-500">Skills:</span> {e.skills.join(', ') || '—'}</p>
              <p><span className="text-slate-500">Certifications:</span> {e.certifications.join(', ') || '—'}</p>
              <p><span className="text-slate-500">Hours:</span> {e.contracted_weekly_hours} h contracted · max {e.max_weekly_hours} h/week · max {e.max_daily_hours ?? '—'} h/day</p>
              <p><span className="text-slate-500">Availability:</span> {e.availability.length ? e.availability.slice(0, 4).map((a) => `${a.date} ${a.start ?? ''}${a.end ? '–' + a.end : ''} ${a.reason ?? a.kind}`).join('; ') : 'no restrictions recorded'}</p>
              <p className="flex flex-wrap items-center gap-1.5 pt-1"><span className="text-slate-500">Rewards:</span> <b>{e.points} points</b>{e.tier && <Chip>{e.tier.label}</Chip>}{e.badges.map((b) => <Chip key={b.id} tone="violet">{b.name}</Chip>)}</p>
            </CardBody>
          </Card>
        ) : (
          <Card><CardHeader title="Organization" /><CardBody className="p-4 text-xs space-y-1">
            <p>{data.organization?.name ?? 'No organization loaded'}</p><p className="text-slate-500">{data.organization?.location} · {data.organization?.timezone}</p></CardBody></Card>
        )}
        <ChangePasswordCard />
        <Card>
          <CardHeader title="Active sessions" />
          <ul className="divide-y divide-slate-100 text-xs">{data.sessions.map((s) => (
            <li key={s.sid} className="px-4 py-2">{s.current && <Chip tone="green">this device</Chip>} {s.user_agent.slice(0, 60) || 'Browser'} · signed in {fmtWhen(s.created_at)} · last active {fmtWhen(s.last_seen)}</li>))}
            {!data.sessions.length && <li className="px-4 py-2 text-slate-500">Demo sign-in sessions are not listed.</li>}</ul>
          <CardBody className="p-4 flex flex-wrap gap-2">
            <Button icon={<LogOut className="w-3.5 h-3.5" />} onClick={() => signOut(false)}>Sign out</Button>
            <Button variant="destructive" onClick={() => signOut(true)}>Sign out everywhere</Button>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

export function ChangePasswordCard({ forced = false, onDone }: { forced?: boolean; onDone?: () => void }) {
  const toast = useToast();
  const [cur, setCur] = useState('');
  const [next, setNext] = useState('');
  const [again, setAgain] = useState('');
  const [busy, setBusy] = useState(false);
  const problem = next && next.length < 8 ? 'At least 8 characters' : next && !(/[A-Za-z]/.test(next) && /\d/.test(next)) ? 'Use letters and digits'
    : again && again !== next ? 'Passwords don’t match' : null;
  async function save(ev: FormEvent) {
    ev.preventDefault();
    setBusy(true);
    try { await api.changePassword(cur, next); toast('Password changed.'); setCur(''); setNext(''); setAgain(''); onDone?.(); }
    catch (err) { toast(errorMessage(err), 'error'); } finally { setBusy(false); }
  }
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-1.5"><KeyRound className="w-4 h-4 text-slate-400" />{forced ? 'Set your own password' : 'Change password'}</span>} />
      <form onSubmit={save}><CardBody className="p-4 space-y-3">
        {forced && <Notice tone="warning">You signed in with a temporary password. Choose your own password to continue.</Notice>}
        <Field label={forced ? 'Temporary password' : 'Current password'}><input type="password" autoComplete="current-password" className="input w-full" value={cur} onChange={(e) => setCur(e.target.value)} required /></Field>
        <Field label="New password" hint="8+ characters, letters and digits"><input type="password" autoComplete="new-password" className="input w-full" value={next} onChange={(e) => setNext(e.target.value)} required /></Field>
        <Field label="Repeat new password" error={problem}><input type="password" autoComplete="new-password" className="input w-full" value={again} onChange={(e) => setAgain(e.target.value)} required /></Field>
        <Button type="submit" variant="primary" disabled={busy || !cur || !next || next !== again || !!problem}>{busy ? 'Saving…' : 'Change password'}</Button>
      </CardBody></form>
    </Card>
  );
}
