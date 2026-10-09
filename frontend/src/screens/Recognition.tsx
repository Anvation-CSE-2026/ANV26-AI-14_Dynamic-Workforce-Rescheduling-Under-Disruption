// Recognition, manager side: domain-specific categories, who earned what and why, and recognizing someone.
import React, { useState } from 'react';
import { Award as AwardIcon, Info } from '../components/common/icons';
import { api, errorMessage } from '../api/client';
import type { RecognitionConfig, RecognitionSummary, Award } from '../api/types';
import { Button } from '../components/common/Button';
import { Card, CardBody, CardHeader } from '../components/common/Card';
import { Modal } from '../components/common/Modal';
import { EmptyState, ErrorState, Spinner, useAsync, usePoll } from '../components/common/States';
import { Why } from '../components/common/Why';
import { useDomain } from '../lib/domain';
import { fmtWhen } from '../lib/format';
import { useToast } from '../lib/toast';

const SIGNAL_TEXT: Record<string, string> = {
  disruption_cover: 'earned automatically when someone takes on work in an approved repair',
  critical_cover: 'earned automatically when the covered work is critical priority',
  prompt_acknowledgement: 'earned automatically for acknowledging a change within 12 hours',
  advance_notice: 'earned automatically for reporting an absence 2+ days ahead',
};

export function Recognition({ refreshKey }: { refreshKey: number }) {
  const { t } = useDomain();
  const toast = useToast();
  const { loading, error, data, reload } = useAsync<{ config: RecognitionConfig; employees: RecognitionSummary[]; recent: Award[] }>(() => api.recognition(), [refreshKey]);
  usePoll(reload, 15000);
  const [give, setGive] = useState<RecognitionSummary | null>(null);
  const [cat, setCat] = useState('');
  const [note, setNote] = useState('');

  if (loading && !data) return <Spinner />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;
  const awardable = data.config.categories.filter((c) => c.managerAwardable);

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">Recognition</h2>
        <p className="text-xs text-slate-500 max-w-2xl">Recognition rewards behaviour that helps the team: covering for colleagues, responding quickly, giving early notice, and contributions you call out.
          Hours worked and overtime earn nothing, and absences never cost points.</p>
      </div>
      <div className="grid lg:grid-cols-[1.4fr_1fr] gap-5 [&>*]:min-w-0">
        <Card>
          <CardHeader title={`${t('employees', 'Employees')}`} subtitle="Points over the last 90 days, by category" />
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-slate-500 bg-slate-50"><tr>
                <th className="text-left font-medium px-4 py-2">{t('employee', 'Employee')}</th>
                <th className="text-left font-medium px-2">Recognized for</th>
                <th className="text-right font-medium px-2">Points</th>
                <th className="text-left font-medium px-2">Level</th>
                <th className="px-4" />
              </tr></thead>
              <tbody>{data.employees.map((e) => (
                <tr key={e.employee_id} className="border-t border-slate-100">
                  <td className="px-4 py-2 font-medium">{e.employee_name}</td>
                  <td className="px-2 text-slate-600">{e.categories.length ? e.categories.map((c) => (
                    <Why key={c.category} text={e.awards.filter((a) => a.category === c.category).slice(0, 4).map((a) => `${a.reason} (+${a.points}, ${a.awarded_by})`).join(' · ')}>
                      <span className="mr-2">{c.label} ×{c.count}</span></Why>)) : <span className="text-slate-400">—</span>}</td>
                  <td className="px-2 text-right tabular-nums font-semibold">{e.points_90d}</td>
                  <td className="px-2">{e.tier ? <Why text={`Benefit: ${e.tier.benefit}`}><span>{e.tier.label}</span></Why> : <span className="text-slate-400">{e.next_tier ? `${e.next_tier.points - e.points_90d} to ${e.next_tier.label}` : ''}</span>}</td>
                  <td className="px-4 text-right"><Button size="sm" onClick={() => { setGive(e); setCat(awardable[0]?.id ?? ''); setNote(''); }}>Recognize</Button></td>
                </tr>))}
              </tbody>
            </table>
          </div>
        </Card>
        <div className="space-y-5">
          <Card>
            <CardHeader title="Categories in this organization" />
            <ul className="divide-y divide-slate-100 text-xs">
              {data.config.categories.map((c) => (
                <li key={c.id} className="px-4 py-2">
                  <div className="flex justify-between gap-2"><b className="font-medium text-slate-800">{c.label}</b><span className="text-slate-500 tabular-nums">+{c.points}</span></div>
                  <p className="text-slate-500">{c.description}{c.signals.length ? `, ${c.signals.map((s) => SIGNAL_TEXT[s] ?? s).join('; ')}` : ', awarded by an admin'}.</p>
                </li>
              ))}
            </ul>
            <CardBody className="p-4 pt-2 text-xs text-slate-600 space-y-1">
              {data.config.tiers.map((tier) => <p key={tier.label}><b>{tier.label}</b> at {tier.points} points: {tier.benefit}</p>)}
              <p className="flex gap-1.5 text-slate-500 pt-1"><Info className="w-3.5 h-3.5 shrink-0 mt-0.5" />Automatic awards are capped at 3 per category per 30 days.</p>
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Recent recognition" />
            {data.recent.length === 0 ? <EmptyState title="Nothing yet" hint="Approve a repair or recognize someone." /> : (
              <ul className="divide-y divide-slate-100 text-xs">
                {data.recent.slice(0, 8).map((a) => (
                  <li key={a.id} className="px-4 py-2 flex gap-2"><AwardIcon className="w-3.5 h-3.5 text-[var(--accent)] mt-0.5 shrink-0" />
                    <span><b className="font-medium">{a.employee_name}</b>: {a.category_label} (+{a.points})<br /><span className="text-slate-500">{a.reason} · {a.awarded_by} · {fmtWhen(a.created_at)}</span></span></li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
      <Modal isOpen={!!give} onClose={() => setGive(null)} title={`Recognize ${give?.employee_name ?? ''}`} subtitle="They'll see this on their dashboard."
             footer={<><Button onClick={() => setGive(null)}>Cancel</Button>
               <Button variant="primary" disabled={!note.trim() || !cat} onClick={async () => {
                 try { await api.recognize(give!.employee_id, cat, note); toast(`${give!.employee_name} recognized.`); setGive(null); reload(); }
                 catch (e) { toast(errorMessage(e), 'error'); }
               }}>Recognize</Button></>}>
        <div className="space-y-3 text-xs">
          <label className="block text-slate-600">Category
            <select className="input w-full mt-1" value={cat} onChange={(e) => setCat(e.target.value)}>
              {awardable.map((c) => <option key={c.id} value={c.id}>{c.label} (+{c.points})</option>)}
            </select>
          </label>
          <label className="block text-slate-600">What it's for (required)
            <input className="input w-full mt-1" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Stayed to hand over the night shift safely" />
          </label>
        </div>
      </Modal>
    </div>
  );
}
