// Constraint analysis: hard rules every option satisfies, soft goals that rank them, and, when no feasible
// repair exists, the bottleneck funnel for each shift that can't be covered.
import React from 'react';
import { AlertOctagon, Check, Hand, Lightbulb, X } from '../common/icons';
import type { ConstraintItem, UnresolvedShift } from '../../api/types';
import { Card, CardBody, CardHeader } from '../common/Card';
import { Why } from '../common/Why';
import { useDomain } from '../../lib/domain';
import { fmtDay } from '../../lib/format';

export function ConstraintChecklist({ hard, soft, unresolvedCount }: {
  hard: ConstraintItem[]; soft: ConstraintItem[]; unresolvedCount: number;
}) {
  return (
    <Card>
      <CardHeader title="Constraint analysis" subtitle="Hard rules can never be broken; soft goals only rank valid repairs" />
      <CardBody className="p-4 grid md:grid-cols-2 gap-5 text-xs">
        <div>
          <h4 className="font-semibold text-slate-800 mb-2">Hard constraints</h4>
          <ul className="space-y-1.5">
            {hard.map((c) => {
              const failed = c.id === 'coverage' && unresolvedCount > 0;
              return (
                <li key={c.id} className="flex items-start gap-2">
                  {failed ? <X className="w-3.5 h-3.5 text-rose-600 mt-0.5 shrink-0" aria-label="not satisfiable" />
                          : <Check className="w-3.5 h-3.5 text-emerald-600 mt-0.5 shrink-0" aria-label="satisfied" />}
                  <Why text={failed
                    ? `${unresolvedCount} shift${unresolvedCount > 1 ? 's' : ''} cannot be covered by anyone without breaking another hard rule. See the analysis below.`
                    : `Every option shown was solved with this rule and re-checked by the validator afterwards: ${c.detail}.`}>
                    <span className={failed ? 'text-rose-700 font-medium' : 'text-slate-700'}>{c.label}</span>
                  </Why>
                </li>
              );
            })}
          </ul>
        </div>
        <div>
          <h4 className="font-semibold text-slate-800 mb-2">Soft goals (ranking)</h4>
          <ul className="space-y-1.5">
            {soft.map((c) => (
              <li key={c.id} className="flex items-baseline justify-between gap-2">
                <Why text={`${c.detail}. Weight ${c.weight} in the objective: a higher weight means the solver gives it more importance when choosing between valid repairs.`}>
                  <span className="text-slate-700">{c.label}</span>
                </Why>
                <span className="tabular-nums text-slate-400">weight {c.weight}</span>
              </li>
            ))}
          </ul>
        </div>
      </CardBody>
    </Card>
  );
}

export function UnresolvedPanel({ items }: { items: UnresolvedShift[] }) {
  const { t } = useDomain();
  if (!items.length) return null;
  return (
    <section aria-label="Unresolved constraint analysis" className="rounded-lg border-2 border-rose-300 bg-white">
      <div className="px-4 py-3 bg-rose-50 border-b border-rose-200 rounded-t-lg flex items-start gap-2">
        <AlertOctagon className="w-5 h-5 text-rose-600 shrink-0" />
        <div>
          <h3 className="text-sm font-semibold text-rose-900">No feasible repair exists under the current constraints</h3>
          <p className="text-xs text-rose-800 mt-0.5">
            ResQWork will not place an unqualified, unavailable or double-booked {t('employee', 'person').toLowerCase()}, and it will not relax a hard rule on its own.
            Here is exactly what blocks each {t('shift', 'shift').toLowerCase()}.
          </p>
        </div>
      </div>
      <div className="divide-y divide-rose-100">
        {items.map((u) => <Unresolved key={u.shift_id} u={u} />)}
      </div>
    </section>
  );
}

function Unresolved({ u }: { u: UnresolvedShift }) {
  const max = Math.max(1, u.total_employees);
  return (
    <div className="p-4 grid lg:grid-cols-[1.1fr_1fr] gap-5 text-xs">
      <div className="space-y-3">
        <div>
          <p className="text-slate-500">{fmtDay(u.date)} {u.start}–{u.end}{u.department ? ` · ${u.department}` : ''} · {u.priority} priority</p>
          <p className="text-sm font-semibold text-slate-900">{u.assignment}</p>
          <p className="text-slate-600 mt-0.5">{u.why_open}</p>
        </div>
        <p className="rounded bg-rose-50 border border-rose-200 px-3 py-2 text-rose-900 font-medium">{u.summary}</p>
        <div>
          <h4 className="font-semibold text-slate-800 mb-1.5">Who could cover it? ({u.total_employees} people checked)</h4>
          <ol className="space-y-1.5" aria-label="Eligibility funnel">
            {u.funnel.map((f, i) => {
              const bottleneck = f.stage === u.bottleneck;
              return (
                <li key={f.stage} className="grid grid-cols-[8.5rem_1fr_2rem] items-center gap-2">
                  <Why text={f.eliminated.length
                    ? <>Ruled out here:<br />{f.eliminated.slice(0, 8).map((b) => <span key={b.employee_id}>{b.name}: {b.detail}<br /></span>)}{f.eliminated.length > 8 ? `…and ${f.eliminated.length - 8} more` : ''}</>
                    : 'Nobody was ruled out at this step.'}>
                    <span className={`${bottleneck ? 'text-rose-700 font-semibold' : 'text-slate-700'}`}>{i + 1}. {f.label}</span>
                  </Why>
                  <span className="relative h-4 bg-slate-100 rounded" aria-hidden>
                    <span className={`absolute inset-y-0 left-0 rounded ${f.remaining ? 'bg-emerald-500' : 'bg-rose-400'}`}
                          style={{ width: `${f.remaining ? (100 * f.remaining) / max : 2}%` }} />
                    <span className="absolute inset-0 px-1.5 flex items-center text-[10px] text-slate-600 truncate">{f.requirement}</span>
                  </span>
                  <span className={`tabular-nums text-right font-semibold ${f.remaining ? 'text-slate-800' : 'text-rose-600'}`}>{f.remaining}</span>
                </li>
              );
            })}
          </ol>
          <p className="mt-1.5 text-[11px] text-slate-500">Bottleneck: <b className="text-rose-700">{u.bottleneck_label}</b></p>
        </div>
      </div>
      <div className="space-y-3">
        <div>
          <h4 className="font-semibold text-slate-800 mb-1.5">Blocking constraints, ranked</h4>
          <ul className="space-y-1.5">
            {u.blocking.map((b) => (
              <li key={b.stage} className="flex items-start justify-between gap-2">
                <span className="text-slate-700">{b.label}</span>
                <span className="text-slate-500 text-right">
                  blocks {b.eliminated}
                  {b.near_misses.length > 0 && (
                    <> · <Why text={b.near_misses.map((m) => `${m.name}: ${m.detail}`).join('; ')}>
                      <span className="text-slate-800">only obstacle for {b.near_misses.map((m) => m.name).join(', ')}</span>
                    </Why></>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h4 className="font-semibold text-slate-800 mb-1.5">Possible resolutions</h4>
          <ul className="space-y-1.5">
            {u.resolutions.map((r) => (
              <li key={r.action} className="flex items-start gap-2">
                {r.kind === 'manual_override' ? <Hand className="w-3.5 h-3.5 text-amber-600 mt-0.5 shrink-0" /> : <Lightbulb className="w-3.5 h-3.5 text-slate-400 mt-0.5 shrink-0" />}
                <span><b className="font-medium text-slate-800">{r.action}</b>
                  {r.kind === 'manual_override' && <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded bg-amber-50 text-amber-800 border border-amber-200">needs an admin decision · not applied automatically</span>}
                  <br /><span className="text-slate-600">{r.detail}</span></span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
