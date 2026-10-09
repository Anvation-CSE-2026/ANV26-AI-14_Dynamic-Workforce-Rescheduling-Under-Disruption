// Demo-only role switcher: sign in as another seeded account of the same organization in one click, so judges
// can watch a request or repair travel between the employee and manager dashboards. Uses the normal login API.
import React, { useEffect, useState } from 'react';
import { Users } from '../common/icons';
import { api, errorMessage, setToken } from '../../api/client';
import type { DemoAccount, DomainId, User } from '../../api/types';
import { useToast } from '../../lib/toast';

const ROLE: Record<string, string> = { operations_manager: 'Admin', admin: 'Admin', department_manager: 'Admin', employee: 'Employee' };

export const isDemoUser = (u: User) => !!u.email?.endsWith('.demo') || u.id.startsWith('demo-');

export function DemoSwitcher({ user, domain, org, onSwitched }: { user: User; domain: DomainId; org?: string; onSwitched: (u: User, token: string) => void }) {
  const toast = useToast();
  const [accounts, setAccounts] = useState<DemoAccount[]>([]);
  useEffect(() => {
    if (isDemoUser(user)) api.demoAccounts().then((a) => setAccounts(a.filter((x) => x.domain === domain && (!org || x.org === org)))).catch(() => {});
  }, [user, domain, org]);
  if (!accounts.length) return null;
  return (
    <label className="inline-flex items-center gap-1.5 text-xs text-slate-600">
      <Users className="w-3.5 h-3.5 text-slate-400" />
      <span className="sr-only">Switch demo user</span>
      <select className="input h-8 max-w-[9.5rem] sm:max-w-[13rem]" value={user.email ?? ''} onChange={async (e) => {
        const a = accounts.find((x) => x.email === e.target.value);
        if (!a) return;
        try {
          const r = await api.login(a.email, a.password);
          setToken(r.token);
          toast(`Signed in as ${a.name} (${ROLE[a.role] ?? a.role}).`, 'info');
          onSwitched(r.user, r.token);
        } catch (err) { toast(errorMessage(err), 'error'); }
      }}>
        {!accounts.some((a) => a.email === user.email) && <option value="">Switch demo user…</option>}
        {accounts.map((a) => <option key={a.email} value={a.email}>{ROLE[a.role] ?? a.role}: {a.name}</option>)}
      </select>
    </label>
  );
}
