// Landing page. One idea carries it: a schedule grid where one shift breaks and exactly one other cell changes.
import React, { useEffect, useMemo, useState } from 'react';
import { ArrowRight, Check, Lock, Upload, X, ShieldCheck, FileClock, Building2, KeyRound, ScanSearch, RotateCcw } from '../components/common/icons';
import { api, errorMessage } from '../api/client';
import type { DemoAccount, DomainId, DomainSummary, Role, User } from '../api/types';
import { Button } from '../components/common/Button';
import { DomainIcon } from '../components/common/DomainIcon';
import { Modal } from '../components/common/Modal';
import { useToast } from '../lib/toast';

const INK = '#0E1B2C';
const ROLE_LABEL: Record<string, string> = { operations_manager: 'Admin / Operations', admin: 'Admin / Operations', department_manager: 'Department manager', employee: 'Employee' };

export function Landing({ onSignedIn, onUpload }: {
  onSignedIn: (user: User, token: string, domain?: DomainId | 'flagship') => void;
  onUpload: (user: User, token: string) => void;
}) {
  const toast = useToast();
  const [domains, setDomains] = useState<DomainSummary[]>([]);
  const [accounts, setAccounts] = useState<DemoAccount[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [signIn, setSignIn] = useState(false);

  useEffect(() => {
    api.domains().then(setDomains).catch((e) => toast(errorMessage(e), 'error'));
    api.demoAccounts().then(setAccounts).catch(() => {});
  }, []);

  async function loginAs(a: DemoAccount) {
    setBusy(a.email);
    try {
      const r = await api.login(a.email, a.password);
      toast(`Signed in as ${a.name} (${ROLE_LABEL[a.role]}).`);
      onSignedIn(r.user, r.token, a.domain);
    } catch (e) { toast(errorMessage(e), 'error'); } finally { setBusy(null); }
  }

  async function openFlagship() {
    setBusy('flagship');
    try {
      const r = await api.login('admin@flagship.demo', 'demo1234');
      toast('Opened the 100-person hospital demo as Admin / Operations.');
      onSignedIn(r.user, r.token, 'flagship');
    } catch (e) { toast(errorMessage(e, 'The flagship demo is only available when demo accounts are enabled.'), 'error'); } finally { setBusy(null); }
  }

  async function openDemo(domain: DomainId, role: Role = 'admin', reset = false) {
    const acct = accounts.find((a) => a.domain === domain && a.role === role);
    if (acct && !reset) return loginAs(acct);
    setBusy(domain);
    try {
      const { user, token } = await api.demoLogin(role, domain, undefined, reset);
      toast(reset ? 'Demo data reset to its starting state.' : 'Demo opened.');
      onSignedIn(user, token, domain);
    } catch (e) { toast(errorMessage(e), 'error'); } finally { setBusy(null); }
  }

  return (
    <div className="min-h-screen bg-[#F6F8FA] text-[#0E1B2C]">
      <header className="sticky top-0 z-30 bg-[#F6F8FA]/90 backdrop-blur border-b border-[#D9E0E8]">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 h-14 flex items-center gap-6">
          <a href="#top" className="flex items-center gap-2 font-semibold tracking-tight">
            <span className="w-7 h-7 rounded-md grid place-items-center text-white text-[11px] font-bold" style={{ background: INK }}>RQ</span>ResQWork
          </a>
          <nav className="hidden md:flex gap-5 text-sm text-slate-600" aria-label="Page sections">
            <a href="#how" className="hover:text-[#0E1B2C]">How it decides</a>
            <a href="#impossible" className="hover:text-[#0E1B2C]">When it can't be done</a>
            <a href="#demo" className="hover:text-[#0E1B2C]">Live demo</a>
          </nav>
          <div className="flex-1" />
          <button className="text-sm text-slate-700 hover:text-[#0E1B2C]" onClick={() => setSignIn(true)}>Sign in</button>
          <a href="#demo" className="hidden sm:inline-flex items-center h-9 px-4 rounded-md text-sm font-medium text-white" style={{ background: INK }}>Open the live demo</a>
        </div>
      </header>

      {/* Hero */}
      <section id="top" className="max-w-6xl mx-auto px-4 sm:px-6 pt-14 pb-16 grid lg:grid-cols-[1fr_1.05fr] gap-12 items-center">
        <div>
          <h1 className="text-[2.6rem] sm:text-[3.4rem] leading-[1.02] font-semibold tracking-[-0.035em]">
            Don't rebuild the schedule. Repair it intelligently.<span className="block text-[#0F766E]">And repair it fairly.</span>
          </h1>
          <p className="mt-6 text-lg leading-relaxed text-slate-600 max-w-[34rem]">
            When someone can't make their shift, ResQWork changes as little of your existing schedule as possible.
            It checks every hard rule, spreads extra work fairly, explains the decision in plain language and waits for an admin to approve it.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <button onClick={openFlagship} disabled={busy === 'flagship'} className="inline-flex items-center gap-2 h-11 px-5 rounded-md text-sm font-medium text-white bg-[#0F766E] hover:bg-[#115E59] disabled:opacity-60">
              {busy === 'flagship' ? 'Opening…' : 'Open the 100-person demo'} <ArrowRight className="w-4 h-4" /></button>
            <a href="#demo" className="inline-flex items-center gap-2 h-11 px-5 rounded-md text-sm font-medium text-white" style={{ background: INK }}>
              Open the live demo <ArrowRight className="w-4 h-4" /></a>
            <button onClick={() => setSignIn(true)} className="inline-flex items-center gap-2 h-11 px-5 rounded-md text-sm font-medium border border-[#C5CFDA] bg-white hover:border-[#0E1B2C]">
              <Upload className="w-4 h-4" /> Repair your own schedule</button>
          </div>
          <p className="mt-6 text-sm text-slate-500">Healthcare, manufacturing, education, technology and logistics. One engine, five industry setups.</p>
        </div>
        <RepairGrid />
      </section>

      {/* The decision flow + a fairness explanation, so judges get the product in 10 seconds */}
      <section aria-label="How a repair is made" className="max-w-6xl mx-auto px-4 sm:px-6 pb-14">
        <ol className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2 text-xs">
          {[['Existing schedule', 'Your roster stays the baseline'], ['Disruption', 'Absence, conflict or gap'], ['AI conflict intelligence', 'Explains why and suggests'],
            ['Constraint validation', 'Hard rules reject candidates'], ['CP-SAT optimization', 'Smallest valid change'], ['Fair repair', 'Recent extra work counts'],
            ['Admin approval', 'Nothing publishes without it']].map(([h, b], i) => (
            <li key={h} className="rounded-lg bg-white border border-[#D9E0E8] p-3">
              <span className="text-[10px] font-mono text-slate-400">0{i + 1}</span>
              <p className="font-semibold text-[#0E1B2C] mt-0.5">{h}</p><p className="text-slate-500 mt-0.5">{b}</p>
            </li>))}
        </ol>
        <div className="mt-6 grid md:grid-cols-2 gap-4 text-sm">
          <div className="rounded-xl bg-white border border-[#D9E0E8] p-5">
            <p className="text-[11px] uppercase tracking-wider text-slate-500">Recommended repair · 100-person hospital</p>
            <p className="mt-1 font-semibold">Meera Pillai covers ICU Ventilator Bay, Fri 07:00–15:00</p>
            <ul className="mt-3 space-y-1 text-xs text-slate-700">
              {['Required skill & certification', 'Available, no double booking', 'Required rest maintained', 'No overtime', 'Only one schedule change', 'Lower recent workload (2 extra covers this month)'].map((x) => (
                <li key={x} className="flex gap-2"><span className="text-emerald-600">✓</span>{x}</li>))}
            </ul>
          </div>
          <div className="rounded-xl bg-white border border-[#D9E0E8] p-5">
            <p className="text-[11px] uppercase tracking-wider text-slate-500">Why not the alternative</p>
            <p className="mt-1 font-semibold">Arjun Menon is valid, but…</p>
            <ul className="mt-3 space-y-1 text-xs text-slate-700">
              <li className="flex gap-2"><span className="text-emerald-600">✓</span>Skill, availability and rest all pass</li>
              <li className="flex gap-2"><span className="text-amber-600">⚠</span>Already did 8 extra covers in the last 30 days</li>
              <li className="flex gap-2"><span className="text-amber-600">⚠</span>Higher recent workload (40 h this week)</li>
            </ul>
            <p className="mt-3 text-xs text-slate-500">Fairness only ranks people who pass every hard rule. Old contributions fade, so volunteering is never a permanent penalty.</p>
          </div>
        </div>
      </section>

      {/* Rebuild vs repair */}
      <section className="bg-white border-y border-[#D9E0E8]">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-16">
          <h2 className="text-2xl sm:text-3xl font-semibold tracking-tight max-w-2xl">Same disruption, two ways to respond.</h2>
          <p className="mt-3 text-slate-600 max-w-2xl">Measured on the hospital demo: one ICU nurse calls in sick for a 12-hour day shift.</p>
          <div className="mt-10 grid md:grid-cols-2 gap-6">
            <Compare title="Traditional scheduling" verdict="Rebuild the roster" changed={15} total={36} tone="rust" points={[
              ['bad', 'Regenerates the roster, moving 16 people who had already planned their week'],
              ['bad', 'No record of why anyone was chosen'],
              ['bad', 'Publishes straight away, or fails silently when it can’t'],
            ]} />
            <Compare title="ResQWork" verdict="Repair the schedule" changed={1} total={36} tone="green" points={[
              ['good', 'Neha Joshi covers the ICU shift: 1 change, no overtime, every rule checked'],
              ['good', 'Explains why, and why not Elena (rest rule) or Hannah (12h overtime)'],
              ['good', 'An admin approves; only the people affected are notified'],
            ]} />
          </div>
        </div>
      </section>

      {/* How it decides */}
      <section id="how" className="max-w-6xl mx-auto px-4 sm:px-6 py-16">
        <h2 className="text-2xl sm:text-3xl font-semibold tracking-tight max-w-2xl">How a repair is decided</h2>
        <p className="mt-3 text-slate-600 max-w-2xl">AI reads the request and writes the explanation. A constraint solver makes the decision. A person approves it.</p>
        <ol className="mt-10 grid sm:grid-cols-2 lg:grid-cols-4 gap-x-6 gap-y-8">
          {[
            ['Understand the disruption', '“Rahul is sick tomorrow” or an employee request becomes a structured absence. If it’s ambiguous, ResQWork asks instead of guessing.'],
            ['Find the impact', 'Only the shifts that overlap the absence are opened. Shifts that have already started are never touched.'],
            ['Check hard constraints', 'Skills, certifications, availability, overlaps, rest and hours limits, including the rules in your policy handbook.'],
            ['Generate candidates', 'OR-Tools CP-SAT searches for valid repairs, including chains where one move frees someone else.'],
            ['Rank by soft goals', 'Fewest changes first, then overtime, fairness and preferences. Alternatives appear only if they offer a real trade-off.'],
            ['Explain from the numbers', 'Hours before and after, rest, skills, and why each other person was ruled out. Nothing is invented.'],
            ['Wait for approval', 'Approve, reject, compare or run a what-if. Nothing is published automatically.'],
            ['Notify and recognize', 'Only affected people get a notice to acknowledge, and people who covered are recognized.'],
          ].map(([h, b], i) => (
            <li key={h} className="border-t-2 pt-4" style={{ borderColor: i === 2 ? '#B4432B' : i === 6 ? '#127A5B' : '#C5CFDA' }}>
              <p className="text-sm text-slate-400 tabular-nums">{i + 1}</p>
              <h3 className="mt-1 font-semibold">{h}</h3>
              <p className="mt-1.5 text-sm text-slate-600 leading-relaxed">{b}</p>
            </li>
          ))}
        </ol>
      </section>

      {/* When it can't be done */}
      <section id="impossible" className="text-white" style={{ background: INK }}>
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-16 grid lg:grid-cols-[1fr_1.1fr] gap-12 items-center">
          <div>
            <h2 className="text-2xl sm:text-3xl font-semibold tracking-tight">When no valid repair exists, it says so.</h2>
            <p className="mt-4 text-slate-300 leading-relaxed max-w-lg">
              ResQWork won’t put an uncertified operator on a CNC line to make the grid look full. It reports
              <b className="text-white"> No feasible repair exists</b>, shows which constraint is the bottleneck and who came closest,
              and lists what an admin could change. It never relaxes a hard rule on its own.
            </p>
          </div>
          <Funnel />
        </div>
      </section>

      {/* Demo */}
      <section id="demo" className="max-w-6xl mx-auto px-4 sm:px-6 py-16">
        <h2 className="text-2xl sm:text-3xl font-semibold tracking-tight">Try it with realistic data</h2>
        <p className="mt-3 text-slate-600 max-w-2xl">Each industry has its own organization, terminology, dashboards, policy handbook and demo accounts.
          Sign in as the admin and as an employee to watch a request, a repair and a recognition move between them.</p>
        <div className="mt-8 grid md:grid-cols-2 lg:grid-cols-3 gap-4">
          {domains.map((d) => {
            const acc = accounts.filter((a) => a.domain === d.id);
            return (
              <div key={d.id} className="rounded-lg border border-[#D9E0E8] bg-white p-5 flex flex-col">
                <div className="flex items-center gap-2" style={{ color: d.accent }}>
                  <DomainIcon name={d.icon} className="w-5 h-5" /><h3 className="font-semibold text-[#0E1B2C]">{d.label}</h3>
                </div>
                <p className="text-sm text-slate-500 mt-1">{d.tagline}</p>
                <div className="mt-4 space-y-1.5 flex-1">
                  {(acc.length ? acc : [{ role: 'admin', name: d.dashboardName, email: '', title: '', password: '', domain: d.id, org: '' } satisfies DemoAccount]).map((a: DemoAccount) => (
                    <button key={a.email || a.role} disabled={!!busy} onClick={() => (a.email ? loginAs(a) : openDemo(d.id))}
                            className="w-full flex items-center justify-between gap-2 rounded-md border border-transparent hover:border-[#C5CFDA] px-2.5 py-1.5 text-left text-sm disabled:opacity-60">
                      <span className="min-w-0"><span className="block font-medium truncate">{a.name}</span>
                        <span className="block text-xs text-slate-500 truncate">{ROLE_LABEL[a.role]}{a.story ? `: ${a.story}` : ''}</span></span>
                      {busy === a.email ? <span className="text-xs text-slate-400">Opening…</span> : <ArrowRight className="w-4 h-4 text-slate-400 shrink-0" />}
                    </button>
                  ))}
                </div>
                <button onClick={() => openDemo(d.id, 'admin', true)} disabled={!!busy}
                        className="mt-3 self-start inline-flex items-center gap-1 text-xs text-slate-500 hover:text-[#0E1B2C]"><RotateCcw className="w-3 h-3" />Reset this demo</button>
              </div>
            );
          })}
        </div>
        {accounts.length > 0 && (
          <details className="mt-6 text-sm text-slate-600">
            <summary className="cursor-pointer">Demo credentials (for signing in from another browser)</summary>
            <div className="mt-3 overflow-x-auto"><table className="text-xs w-full max-w-3xl">
              <thead className="text-slate-500"><tr><th className="text-left font-medium py-1 pr-4">Industry</th><th className="text-left font-medium pr-4">Role</th><th className="text-left font-medium pr-4">Email</th><th className="text-left font-medium">Password</th></tr></thead>
              <tbody>{accounts.map((a) => <tr key={a.email} className="border-t border-[#E4E9EF]"><td className="py-1 pr-4">{a.domain}</td><td className="pr-4">{ROLE_LABEL[a.role]}: {a.name}</td><td className="pr-4">{a.email}</td><td>{a.password}</td></tr>)}</tbody>
            </table></div>
          </details>
        )}
      </section>

      {/* Trust */}
      <section className="bg-white border-t border-[#D9E0E8]">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-14 grid sm:grid-cols-2 lg:grid-cols-4 gap-8 text-sm">
          {([
            [ShieldCheck, 'Validated twice', 'Every option is solved under the hard rules, then the whole schedule is checked again before you see it.'],
            [KeyRound, 'Role-based access', 'Admins repair and approve. Employees only see their own schedule and requests.'],
            [Building2, 'Organization isolation', 'Every record is scoped to its organization; API keys stay on the server.'],
            [FileClock, 'Full audit trail', 'Disruptions, repairs, what-ifs, approvals and acknowledgements are all logged with who did them.'],
          ] as const).map(([Icon, h, b]) => (
            <div key={h}><Icon className="w-5 h-5 text-slate-500" /><h3 className="mt-2 font-semibold">{h}</h3><p className="mt-1 text-slate-600 leading-relaxed">{b}</p></div>
          ))}
        </div>
      </section>
      <footer className="max-w-6xl mx-auto px-4 sm:px-6 py-8 text-xs text-slate-500">ResQWork: workforce schedule repair.</footer>

      <SignInModal open={signIn} onClose={() => setSignIn(false)} onSignedIn={onSignedIn} onUpload={onUpload} />
    </div>
  );
}

/** Hero illustration: a week where one shift breaks and exactly one other cell changes. */
function RepairGrid() {
  const people = ['Rahul S.', 'Neha J.', 'Elena R.', 'Carlos M.', 'Hannah S.'];
  const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'];
  // [person][day]: shift label or '' (off)
  const base = [
    ['ICU', 'ICU', '', 'ICU', 'ICU'],
    ['', 'ICU', '', '', ''],
    ['ICU·N', '', 'ICU·N', 'ICU·N', ''],
    ['ED', 'ED', 'ED', '', 'ED'],
    ['ICU', '', 'ICU', 'ICU', 'ICU'],
  ];
  const reduce = useMemo(() => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches, []);
  const [step, setStep] = useState(reduce ? 3 : 0);
  useEffect(() => {
    if (reduce) return;
    const times = [1200, 1500, 1700, 4200];
    const t = setTimeout(() => setStep((s) => (s + 1) % 4), times[step]);
    return () => clearTimeout(t);
  }, [step, reduce]);
  const captions = ['Your existing schedule', 'Thursday: Rahul calls in sick', 'Checking 17 nurses against every rule…', 'Neha covers it: 1 change, everything else stays as it was.'];
  return (
    <figure className="rounded-xl bg-white border border-[#D9E0E8] shadow-[0_1px_0_#D9E0E8,0_24px_48px_-24px_rgba(14,27,44,0.25)] p-5 sm:p-6" aria-label="Animated example of a schedule repair">
      <div className="grid grid-cols-[5.5rem_repeat(5,1fr)] gap-1.5 text-xs">
        <span />
        {days.map((d) => <span key={d} className={`text-center pb-1 ${d === 'Thu' && step > 0 ? 'text-[#0E1B2C] font-semibold' : 'text-slate-400'}`}>{d}</span>)}
        {people.map((p, i) => (
          <React.Fragment key={p}>
            <span className="text-slate-600 self-center truncate">{p}</span>
            {days.map((d, j) => {
              const v = base[i][j];
              const broken = i === 0 && j === 3 && step >= 1;
              const fixed = i === 1 && j === 3 && step >= 3;
              const checking = step === 2 && j === 3 && i > 0;
              return (
                <span key={d} className={`h-9 rounded-md grid place-items-center transition-colors duration-500 ${
                  broken ? 'bg-[#F7E3DE] text-[#B4432B] line-through' :
                  fixed ? 'bg-[#127A5B] text-white font-semibold' :
                  checking ? 'bg-[#EEF2F6] text-slate-500 ring-1 ring-[#C5CFDA]' :
                  v ? 'bg-[#EEF2F6] text-slate-600' : 'bg-transparent border border-dashed border-[#E1E6EC]'}`}>
                  {fixed ? 'ICU' : v}
                </span>
              );
            })}
          </React.Fragment>
        ))}
      </div>
      <figcaption className="mt-4 h-5 text-sm font-medium" aria-live="polite" style={{ color: step === 1 ? '#B4432B' : step === 3 ? '#127A5B' : INK }}>
        {captions[step]}
      </figcaption>
    </figure>
  );
}

function Compare({ title, verdict, changed, total, tone, points }: {
  title: string; verdict: string; changed: number; total: number; tone: 'rust' | 'green'; points: [string, string][];
}) {
  const color = tone === 'rust' ? '#B4432B' : '#127A5B';
  const cells = Array.from({ length: total }, (_, i) => i);
  const hit = new Set(tone === 'rust' ? [1, 3, 4, 7, 9, 12, 14, 15, 18, 21, 23, 26, 28, 31, 33] : [21]);
  return (
    <div className="rounded-lg border border-[#D9E0E8] p-6">
      <p className="text-sm text-slate-500">{title}</p>
      <h3 className="text-xl font-semibold mt-0.5">{verdict}</h3>
      <div className="mt-5 grid grid-cols-12 gap-1" role="img" aria-label={`${changed} of ${total} assignments changed`}>
        {cells.map((i) => <span key={i} className="h-4 rounded-sm" style={{ background: hit.has(i) ? color : '#E8EDF2' }} />)}
      </div>
      <p className="mt-3 text-sm"><b style={{ color }} className="text-2xl font-semibold tabular-nums">{changed}</b> <span className="text-slate-600">of {total} assignments changed</span></p>
      <ul className="mt-5 space-y-2 text-sm text-slate-700">
        {points.map(([k, p]) => <li key={p} className="flex gap-2">{k === 'good' ? <Check className="w-4 h-4 mt-0.5 shrink-0 text-[#127A5B]" /> : <X className="w-4 h-4 mt-0.5 shrink-0 text-[#B4432B]" />}{p}</li>)}
      </ul>
    </div>
  );
}

function Funnel() {
  const steps = [['Operators checked', 5], ['Have CNC Operation', 3], ['Hold Safety Level 2', 2], ['Available on Friday', 1], ['Not already on a mandatory line', 0]] as const;
  return (
    <div className="rounded-xl bg-white/5 border border-white/10 p-6">
      <p className="text-sm text-slate-300">Line 1 · CNC Machining, Fri 06:00–14:00</p>
      <ul className="mt-4 space-y-2.5">
        {steps.map(([label, n]) => (
          <li key={label} className="grid grid-cols-[1fr_auto] gap-3 items-center text-sm">
            <span className="relative h-8 rounded-md overflow-hidden bg-white/5">
              <span className="absolute inset-y-0 left-0 rounded-md" style={{ width: `${Math.max(6, (n / 5) * 100)}%`, background: n ? 'rgba(18,122,91,0.85)' : '#B4432B' }} />
              <span className="relative z-10 px-3 leading-8">{label}</span>
            </span>
            <span className={`tabular-nums w-6 text-right font-semibold ${n ? '' : 'text-[#F2A38F]'}`}>{n}</span>
          </li>
        ))}
      </ul>
      <p className="mt-5 text-sm"><ScanSearch className="inline w-4 h-4 mr-1 -mt-0.5" /><b>No feasible repair exists.</b> <span className="text-slate-300">Bottleneck: the only certified, available operator is already running Line 2.</span></p>
      <p className="mt-2 text-sm text-slate-300">Suggested: ask Asha whether she can come in, free up Bala by covering Line 2, or approve supervised cover for Chitra (an admin’s decision).</p>
    </div>
  );
}

function SignInModal({ open, onClose, onSignedIn, onUpload }: {
  open: boolean; onClose: () => void;
  onSignedIn: (user: User, token: string) => void; onUpload: (user: User, token: string) => void;
}) {
  const toast = useToast();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [who, setWho] = useState<'admin' | 'employee'>('admin');
  const [form, setForm] = useState({ email: '', password: '', name: '' });
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const res = mode === 'login' ? await api.login(form.email, form.password)
                                   : await api.register(form.email, form.password, form.name || form.email, 'admin');
      toast(mode === 'login' ? 'Signed in.' : 'Account created.');
      res.user.org ? onSignedIn(res.user, res.token) : onUpload(res.user, res.token);
    } catch (err) { toast(errorMessage(err), 'error'); } finally { setBusy(false); }
  }
  return (
    <Modal isOpen={open} onClose={onClose} title="Sign in to ResQWork" subtitle="Admins upload their own schedule (CSV, XLSX or JSON); employees sign in to see theirs.">
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-2" role="group" aria-label="I am">
          {([['admin', 'Admin / Operations', 'Upload your schedule, repair it, manage people'], ['employee', 'Employee', 'See your shifts, requests and rewards']] as const).map(([k, l, d]) => (
            <button key={k} type="button" aria-pressed={who === k} onClick={() => { setWho(k); if (k === 'employee') setMode('login'); }}
                    className={`text-left rounded-md border p-2.5 ${who === k ? 'border-[#0E1B2C] bg-slate-50' : 'border-slate-200 hover:border-slate-300'}`}>
              <span className="block text-xs font-semibold text-slate-900">{l}</span><span className="block text-[11px] text-slate-500">{d}</span>
            </button>))}
        </div>
        {who === 'employee' && <p className="text-[11px] text-slate-600 bg-slate-50 border border-slate-200 rounded p-2">Use the sign-in ID and temporary password your admin gave you (from <b>Employees → Create employee logins</b>). You'll set your own password the first time.</p>}
        {who === 'admin' && <div className="inline-flex p-0.5 bg-slate-100 rounded text-xs">
          {(['login', 'register'] as const).map((m) => (
            <button key={m} onClick={() => setMode(m)} className={`px-3 py-1 rounded ${mode === m ? 'bg-white shadow-2xs font-semibold' : 'text-slate-600'}`}>
              {m === 'login' ? 'Sign in' : 'Create account'}</button>
          ))}
        </div>}
        <form onSubmit={submit} className="space-y-2.5 text-xs">
          {mode === 'register' && <label className="block text-slate-600">Name<input className="input w-full mt-1" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>}
          <label className="block text-slate-600">{who === 'employee' ? 'Email or sign-in ID' : 'Email'}<input type="email" required autoComplete="email" className="input w-full mt-1" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
          <label className="block text-slate-600">Password<input type="password" required minLength={8} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} className="input w-full mt-1" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></label>
          <Button type="submit" variant="primary" size="lg" className="w-full" disabled={busy} icon={<Lock className="w-3.5 h-3.5" />}>{mode === 'login' ? 'Sign in' : 'Create admin account'}</Button>
        </form>
        {who === 'admin' && <GoogleButton onToken={async (tok) => {
          try { const r = await api.googleLogin(tok); r.user.org ? onSignedIn(r.user, r.token) : onUpload(r.user, r.token); }
          catch (e) { toast(errorMessage(e), 'error'); }
        }} />}
        {who === 'admin' && <div className="pt-3 border-t border-slate-100">
          <Button icon={<Upload className="w-3.5 h-3.5" />} className="w-full" onClick={async () => {
            try { const { user, token } = await api.demoLogin('admin'); onUpload(user, token); } catch (e) { toast(errorMessage(e), 'error'); }
          }}>Skip sign-in: upload a dataset as a demo admin</Button>
        </div>}
      </div>
    </Modal>
  );
}

function GoogleButton({ onToken }: { onToken: (idToken: string) => void }) {
  const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID;
  const ref = React.useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!clientId) return;
    const s = document.createElement('script');
    s.src = 'https://accounts.google.com/gsi/client';
    s.async = true;
    s.onload = () => {
      const g = (window as GoogleWindow).google;
      g?.accounts.id.initialize({ client_id: clientId, callback: (r: { credential: string }) => onToken(r.credential) });
      if (ref.current) g?.accounts.id.renderButton(ref.current, { theme: 'outline', size: 'large', width: 320 });
    };
    document.body.appendChild(s);
  }, [clientId]);
  if (!clientId) return null;
  return <div className="flex justify-center" ref={ref} />;
}

/** Google Identity Services, loaded at runtime from accounts.google.com (only the calls we use). */
type GoogleWindow = Window & { google?: { accounts: { id: {
  initialize(o: { client_id: string; callback: (r: { credential: string }) => void }): void;
  renderButton(el: HTMLElement, o: Record<string, string | number>): void;
} } } };
