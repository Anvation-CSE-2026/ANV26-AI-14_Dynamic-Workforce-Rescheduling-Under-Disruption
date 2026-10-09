import React from 'react';
import {
  LayoutDashboard, Users, ClipboardList, CalendarDays, Wrench, ShieldCheck, History, BarChart3, LogOut, Mic, RefreshCcw, Inbox, Award,
  AlertTriangle, UserPlus, SlidersHorizontal, Bell, User as UserIcon,
} from '../common/icons';
import { Avatar } from '../common/ui';
import type { User, WorkspaceSummary } from '../../api/types';
import { useDomain } from '../../lib/domain';
import { DomainIcon } from '../common/DomainIcon';
import { DemoSwitcher } from './DemoSwitcher';

export type Screen = 'dashboard' | 'sub0' | 'sub1' | 'schedule' | 'repair' | 'requests' | 'recognition' | 'policies' | 'versions' | 'analytics'
  | 'conflicts' | 'repair_center' | 'workforce' | 'employees' | 'constraints' | 'notifications' | 'profile';

export function Shell({ user, workspace, screen, onNavigate, onLogout, onSwitchIndustry, onVoice, repairBadge, requestBadge, onSwitched, children }: {
  user: User;
  workspace: WorkspaceSummary;
  screen: Screen;
  onNavigate: (s: Screen) => void;
  onLogout: () => void;
  onSwitchIndustry: () => void;
  onVoice: () => void;
  repairBadge?: number;
  requestBadge?: number;
  onSwitched: (u: User, token: string) => void;
  children: React.ReactNode;
}) {
  const { config, t } = useDomain();
  const subs = config?.subDashboards ?? [];
  type Item = { id: Screen; label: string; icon: React.ReactNode; badge?: number; group: string };
  const items: Item[] = [
    { id: 'dashboard', label: config?.dashboardName ?? 'Command Center', icon: <LayoutDashboard className="w-4 h-4" />, group: 'Operations' },
    ...subs.slice(0, 2).map((s, i): Item => ({ id: (`sub${i}` as Screen), label: s.name, icon: i === 0 ? <Users className="w-4 h-4" /> : <ClipboardList className="w-4 h-4" />, group: 'Operations' })),
    { id: 'conflicts', label: 'Conflicts (AI assistant)', icon: <AlertTriangle className="w-4 h-4" />, badge: repairBadge, group: 'Operations' },
    { id: 'repair_center', label: 'Repair center', icon: <Wrench className="w-4 h-4" />, group: 'Operations' },
    { id: 'workforce', label: 'Workforce requests', icon: <UserPlus className="w-4 h-4" />, group: 'Operations' },
    { id: 'requests', label: 'Requests', icon: <Inbox className="w-4 h-4" />, badge: requestBadge, group: 'Operations' },
    { id: 'schedule', label: `${t('shift', 'Shift')} schedule`, icon: <CalendarDays className="w-4 h-4" />, group: 'Workforce data' },
    { id: 'employees', label: 'Employees & imports', icon: <Users className="w-4 h-4" />, group: 'Workforce data' },
    { id: 'constraints', label: 'Constraint center', icon: <SlidersHorizontal className="w-4 h-4" />, group: 'Workforce data' },
    { id: 'policies', label: 'Policy intelligence', icon: <ShieldCheck className="w-4 h-4" />, group: 'Workforce data' },
    { id: 'recognition', label: 'Rewards & Recognition', icon: <Award className="w-4 h-4" />, group: 'Insights' },
    { id: 'notifications', label: 'Notifications', icon: <Bell className="w-4 h-4" />, group: 'Insights' },
    { id: 'analytics', label: 'Analytics', icon: <BarChart3 className="w-4 h-4" />, group: 'Insights' },
    { id: 'versions', label: 'Schedules & audit', icon: <History className="w-4 h-4" />, group: 'Insights' },
    { id: 'profile', label: 'My profile', icon: <UserIcon className="w-4 h-4" />, group: 'Account' },
  ];
  const current = items.find((i) => i.id === screen)?.label ?? (screen === 'repair' ? 'Repair details' : '');
  return (
    <div className="min-h-screen flex bg-slate-50">
      <aside className="w-64 shrink-0 bg-white border-r border-slate-200 flex flex-col max-lg:hidden" aria-label="Main navigation">
        <div className="px-4 py-4 border-b border-slate-100">
          <div className="flex items-center gap-2">
            <span className="w-7 h-7 rounded bg-slate-900 text-white grid place-items-center text-xs font-bold">RQ</span>
            <div>
              <p className="text-sm font-semibold tracking-tight text-slate-900">ResQWork</p>
              <p className="text-[10px] text-slate-500 uppercase tracking-wider">Schedule repair intelligence</p>
            </div>
          </div>
        </div>
        <div className="px-4 py-3 border-b border-slate-100">
          <div className="flex items-center gap-2 text-[var(--accent)]">
            <DomainIcon name={config?.icon} className="w-4 h-4" />
            <span className="text-xs font-semibold">{config?.label}</span>
          </div>
          <p className="text-xs text-slate-700 mt-1 truncate" title={workspace.organization.name}>{workspace.organization.name}</p>
          <p className="text-[11px] text-slate-500">Schedule {workspace.version}, {workspace.counts.employees} {t('employees', 'employees').toLowerCase()}</p>
        </div>
        <nav className="flex-1 p-2 space-y-0.5 overflow-y-auto">
          {items.map((it, i) => (<React.Fragment key={it.id}>
            {(i === 0 || items[i - 1].group !== it.group) && <p className="px-2.5 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">{it.group}</p>}
            <button onClick={() => onNavigate(it.id)} aria-current={screen === it.id ? 'page' : undefined}
                    className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded text-xs font-medium text-left transition-colors ${
                      screen === it.id ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'}`}>
              {it.icon}
              <span className="flex-1 truncate">{it.label}</span>
              {!!it.badge && <span className="text-[10px] px-1.5 rounded bg-rose-100 text-rose-700 font-mono">{it.badge}</span>}
            </button>
          </React.Fragment>))}
        </nav>
        <div className="p-3 border-t border-slate-100 space-y-1">
          <button onClick={onSwitchIndustry} className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded text-xs text-slate-600 hover:bg-slate-100">
            <RefreshCcw className="w-3.5 h-3.5" /> Switch industry / dataset
          </button>
          <button onClick={onLogout} className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded text-xs text-slate-600 hover:bg-slate-100">
            <LogOut className="w-3.5 h-3.5 shrink-0" /> <span className="text-left truncate">Sign out ({user.name ?? user.role})</span>
          </button>
        </div>
      </aside>
      <div className="flex-1 min-w-0 flex flex-col">
        <header className="h-14 bg-white border-b border-slate-200 px-4 sm:px-5 flex items-center gap-3 min-w-0">
          <div className="lg:hidden min-w-0 flex-1">
            <select aria-label="Navigate" className="text-xs border border-slate-200 rounded px-2 py-1 max-w-full" value={screen}
                    onChange={(e) => onNavigate(e.target.value as Screen)}>
              {items.map((it) => <option key={it.id} value={it.id}>{it.label}</option>)}
            </select>
          </div>
          <h1 className="text-sm font-semibold text-slate-900 truncate max-lg:hidden">{current}</h1>
          <span className="text-[11px] text-slate-500 max-md:hidden">
            {workspace.reference_date && `Today ${workspace.reference_date}${workspace.reference_time ? ` · now ${workspace.reference_time}` : ''}`}
          </span>
          <div className="flex-1" />
          <DemoSwitcher user={user} domain={workspace.domain} org={workspace.org} onSwitched={onSwitched} />
          <button onClick={onVoice} className="inline-flex items-center gap-1.5 text-xs px-3 h-8 rounded border border-slate-200 hover:bg-slate-50 text-slate-700">
            <Mic className="w-3.5 h-3.5 text-[var(--accent)]" /> <span className="max-sm:sr-only">Voice agent</span>
          </button>
          <button onClick={() => onNavigate('profile')} className="flex items-center gap-2 text-[11px] px-1.5 py-1 rounded hover:bg-slate-100" aria-label="My profile">
            <Avatar name={user.name} src={user.avatar} size={24} /><span className="text-slate-600 max-md:hidden">Admin / Operations</span>
          </button>
        </header>
        <main className="flex-1 p-4 sm:p-5 min-w-0">{children}</main>
      </div>
    </div>
  );
}
