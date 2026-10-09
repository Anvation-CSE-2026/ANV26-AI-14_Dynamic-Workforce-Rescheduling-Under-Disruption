// App flow: Landing (demo or sign-in) → Onboarding (upload/validate/preview) → domain workspace.
// Employees get their own portal; managers get the domain command center + two role sub-dashboards.
import React, { useCallback, useEffect, useState } from 'react';
import { api, hasToken, onAuthEvent, setToken } from './api/client';
import type { StaffingGap, User, WorkspaceSummary } from './api/types';
import { isAdmin } from './api/types';
import { Shell, type Screen } from './components/layout/Shell';
import { Spinner } from './components/common/States';
import { VoiceAgent } from './components/voice/VoiceAgent';
import { DomainProvider } from './lib/domain';
import { ToastProvider, useToast } from './lib/toast';
import { Analytics } from './screens/Analytics';
import { Dashboard } from './screens/Dashboard';
import { EmployeePortal } from './screens/EmployeePortal';
import { Landing } from './screens/Landing';
import { Onboarding } from './screens/Onboarding';
import { Policies } from './screens/Policies';
import { Repair } from './screens/Repair';
import { Schedule } from './screens/Schedule';
import { SubDashboard } from './screens/SubDashboard';
import { Versions } from './screens/Versions';
import { Conflicts } from './screens/Conflicts';
import { ConstraintCenter } from './screens/ConstraintCenter';
import { Employees } from './screens/Employees';
import { Notifications } from './screens/Notifications';
import { ChangePasswordCard, Profile } from './screens/Profile';
import { RepairCenter } from './screens/RepairCenter';
import { RequestsHub } from './screens/RequestsHub';
import { Rewards } from './screens/Rewards';
import { Workforce } from './screens/Workforce';

type Phase = 'boot' | 'landing' | 'onboarding' | 'app' | 'password';

function Root() {
  const toast = useToast();
  const [phase, setPhase] = useState<Phase>('boot');
  const [user, setUser] = useState<User | null>(null);
  const [ws, setWs] = useState<WorkspaceSummary | null>(null);
  const [screen, setScreen] = useState<Screen>('dashboard');
  const [proposalId, setProposalId] = useState<string>();
  const [refreshKey, setRefreshKey] = useState(0);
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [openCount, setOpenCount] = useState(0);
  const [requestCount, setRequestCount] = useState(0);

  const [gap, setGap] = useState<StaffingGap | null>(null);

  const enter = useCallback(async (u: User) => {
    setUser(u);
    if (u.must_change_password) { setPhase('password'); return; }
    try {
      const w = await api.workspace();
      setWs(w);
      setScreen('dashboard');
      setPhase('app');
    } catch {
      setPhase(isAdmin(u.role) ? 'onboarding' : 'landing');
    }
  }, []);

  useEffect(() => {
    if (!hasToken()) { setPhase('landing'); return; }
    api.me().then(enter).catch(() => { setToken(null); setPhase('landing'); });
  }, [enter]);

  // 401 anywhere → back to sign-in; temporary password → force a change before anything else.
  useEffect(() => onAuthEvent((kind) => {
    if (kind === 'unauthorized') { setToken(null); setUser(null); setWs(null); setPhase('landing'); }
    else setPhase('password');
  }), []);

  const changed = useCallback(() => {
    setRefreshKey((k) => k + 1);
    api.workspace().then(setWs).catch(() => {});
  }, []);

  // Badges stay in sync with other users' actions (e.g. an employee filing a request) via a light poll.
  useEffect(() => {
    if (phase !== 'app' || !user || user.role === 'employee') return;
    const tick = () => {
      api.disruptions().then((d) => setOpenCount(d.filter((x) => x.status === 'open').length)).catch(() => {});
      api.availabilityRequests().then((r) => setRequestCount(r.filter((x) => x.status === 'pending' || x.status === 'needs_review').length)).catch(() => {});
    };
    tick();
    const id = setInterval(tick, 10000);
    return () => clearInterval(id);
  }, [phase, refreshKey, user]);

  const switched = useCallback((u: User, token: string) => {
    setToken(token);
    setVoiceOpen(false);
    setProposalId(undefined);
    setRefreshKey((k) => k + 1);
    enter(u);
  }, [enter]);

  function logout() {
    api.logout().catch(() => {});
    setToken(null);
    setUser(null);
    setWs(null);
    setVoiceOpen(false);
    setPhase('landing');
  }

  if (phase === 'boot') return <div className="min-h-screen grid place-items-center"><Spinner label="Starting ResQWork…" /></div>;

  if (phase === 'password' && user) {
    return (
      <div className="min-h-screen grid place-items-center p-4 bg-slate-50">
        <div className="w-full max-w-md space-y-3">
          <p className="text-sm font-semibold text-slate-900">Welcome to ResQWork, {user.name ?? user.email}</p>
          <ChangePasswordCard forced onDone={() => { api.me().then((u) => enter({ ...u, must_change_password: false })).catch(logout); }} />
          <button className="text-xs text-slate-500 hover:underline" onClick={logout}>Sign out</button>
        </div>
      </div>
    );
  }

  if (phase === 'landing') {
    return <Landing
      onSignedIn={(u: User, token: string) => { setToken(token); enter(u); }}
      onUpload={(u, token) => { setToken(token); setUser(u); setPhase('onboarding'); }} />;
  }

  if (phase === 'onboarding') {
    return <Onboarding onDone={(w) => { setWs(w); setScreen('dashboard'); setPhase('app'); toast(`${w.organization.name} is ready.`); }}
                       onCancel={ws ? () => setPhase('app') : logout} />;
  }

  if (!user || !ws) return null;

  if (user.role === 'employee') {
    return <DomainProvider config={ws.config}><EmployeePortal user={user} workspace={ws} onLogout={logout} onSwitched={switched} /></DomainProvider>;
  }

  const go = (s: Screen) => { setScreen(s); if (s !== 'repair') setProposalId(undefined); window.scrollTo(0, 0); };
  const repair = (id?: string) => { setProposalId(id); setScreen('repair'); window.scrollTo(0, 0); };

  return (
    <DomainProvider config={ws.config}>
      <Shell user={user} workspace={ws} screen={screen} onNavigate={go} onLogout={logout} repairBadge={openCount}
             requestBadge={requestCount} onSwitched={switched}
             onSwitchIndustry={() => (isAdmin(user.role) ? setPhase('onboarding') : logout())}
             onVoice={() => setVoiceOpen((v) => !v)}>
        {screen === 'dashboard' && <Dashboard workspace={ws} onRepair={repair} refreshKey={refreshKey} onChanged={changed} onRequests={() => go('requests')} onNavigate={(t) => go(t)} />}
        {screen === 'sub0' && <SubDashboard index={0} refreshKey={refreshKey} />}
        {screen === 'sub1' && <SubDashboard index={1} refreshKey={refreshKey} />}
        {screen === 'schedule' && <Schedule refreshKey={refreshKey} />}
        {screen === 'repair' && <Repair proposalId={proposalId} onChanged={changed} onGoDashboard={() => go('dashboard')} />}
        {screen === 'requests' && <RequestsHub refreshKey={refreshKey} onChanged={changed} onRepair={() => go('dashboard')} />}
        {screen === 'recognition' && <Rewards refreshKey={refreshKey} onChanged={changed} />}
        {screen === 'conflicts' && <Conflicts refreshKey={refreshKey} onRepair={repair} onChanged={changed} onWorkforce={(g) => { setGap(g ?? null); go('workforce'); }} />}
        {screen === 'repair_center' && <RepairCenter refreshKey={refreshKey} onView={repair} onChanged={changed} />}
        {screen === 'workforce' && <Workforce refreshKey={refreshKey} prefill={gap} onChanged={changed} />}
        {screen === 'employees' && <Employees refreshKey={refreshKey} onChanged={changed} />}
        {screen === 'constraints' && <ConstraintCenter refreshKey={refreshKey} onChanged={changed} />}
        {screen === 'notifications' && <Notifications refreshKey={refreshKey} />}
        {screen === 'profile' && <Profile onLogout={logout} onUpdated={() => api.me().then(setUser).catch(() => {})} />}
        {screen === 'policies' && <Policies user={user} />}
        {screen === 'versions' && <Versions refreshKey={refreshKey} />}
        {screen === 'analytics' && <Analytics refreshKey={refreshKey} />}
      </Shell>
      <VoiceAgent open={voiceOpen} onClose={() => setVoiceOpen(false)} onAction={changed}
                  onNavigate={(n) => { if (n.screen === 'repair') repair(n.proposal_id); else go(n.screen as Screen); }} />
    </DomainProvider>
  );
}

export default function App() {
  return <ToastProvider><Root /></ToastProvider>;
}
