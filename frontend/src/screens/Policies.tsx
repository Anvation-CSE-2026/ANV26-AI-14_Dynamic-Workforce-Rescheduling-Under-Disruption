// Policy intelligence: which documents are loaded, which rules were extracted (with verbatim quotes), conflicts,
// and grounded search. "No applicable policy found" is a real answer, not an error.
import React, { useState } from 'react';
import { FileText, Search, Upload, ShieldCheck, AlertTriangle } from '../components/common/icons';
import { api, errorMessage } from '../api/client';
import type { PolicyOverview, PolicySearch, User } from '../api/types';
import { Button } from '../components/common/Button';
import { Card, CardBody, CardHeader } from '../components/common/Card';
import { EmptyState, ErrorState, Spinner, useAsync } from '../components/common/States';
import { useDomain } from '../lib/domain';
import { titleCase } from '../lib/format';
import { useToast } from '../lib/toast';

export function Policies({ user }: { user: User }) {
  const { config } = useDomain();
  const toast = useToast();
  const { loading, error, data, reload } = useAsync<PolicyOverview>(() => api.policies());
  const [q, setQ] = useState('');
  const [res, setRes] = useState<PolicySearch | null>(null);
  const [busy, setBusy] = useState(false);

  async function search(e: React.FormEvent) {
    e.preventDefault();
    if (!q.trim()) return;
    setBusy(true);
    try { setRes(await api.policySearch(q)); } catch (err) { toast(errorMessage(err), 'error'); } finally { setBusy(false); }
  }

  if (loading) return <Spinner />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;

  return (
    <div className="space-y-5">
      <div className="grid lg:grid-cols-[1fr_1.3fr] gap-5">
        <Card>
          <CardHeader title="Policy documents" subtitle={`Mode: ${data.mode}`}
                      action={user.role === 'admin' && (
                        <label className="inline-flex items-center gap-1.5 text-xs px-3 h-8 rounded border border-slate-200 hover:bg-slate-50 cursor-pointer">
                          <Upload className="w-3.5 h-3.5" /> Upload
                          <input type="file" accept=".md,.txt" className="sr-only" onChange={async (e) => {
                            const f = e.target.files?.[0];
                            if (!f) return;
                            try { const r = await api.uploadPolicy(f); toast(`${r.title}: ${r.sections} sections indexed.`); reload(); }
                            catch (err) { toast(errorMessage(err), 'error'); }
                          }} />
                        </label>)} />
          <ul className="divide-y divide-slate-100 text-xs">
            {data.documents.map((d) => (
              <li key={d.policy_id} className="px-4 py-2.5 flex items-start gap-2">
                <FileText className="w-4 h-4 text-slate-400 shrink-0" />
                <div><p className="font-medium text-slate-900">{d.title}</p><p className="text-slate-500">v{d.version}{d.effective_date ? ` · effective ${d.effective_date}` : ''} · {d.chunks} sections</p></div>
              </li>
            ))}
            {data.documents.length === 0 && <li><EmptyState title="No policies loaded" hint="Base scheduling rules still apply." /></li>}
          </ul>
        </Card>
        <Card>
          <CardHeader title="Ask the policy handbook" subtitle="Answers cite the exact section, or say nothing applies" />
          <CardBody className="p-4 space-y-3 text-xs">
            <form onSubmit={search} className="flex gap-2">
              <label htmlFor="pq" className="sr-only">Policy question</label>
              <div className="relative flex-1">
                <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-slate-400" />
                <input id="pq" className="input w-full pl-8" value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. minimum rest between shifts" />
              </div>
              <Button type="submit" disabled={busy}>{busy ? 'Searching…' : 'Search'}</Button>
            </form>
            {res && (res.status === 'no_applicable_policy'
              ? <p className="rounded border border-slate-200 bg-slate-50 p-2.5 text-slate-600">{res.message}</p>
              : <ul className="space-y-2">{res.hits.slice(0, 4).map((h, i) => (
                  <li key={i} className="rounded border border-slate-200 p-2.5">
                    <p className="font-medium text-slate-900">{h.citation} <span className="text-slate-400 font-normal">· {Math.round(h.confidence * 100)}% match</span></p>
                    <p className="text-slate-600 mt-1 whitespace-pre-line">{h.text}</p>
                  </li>))}</ul>)}
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader title={<span className="flex items-center gap-1.5"><ShieldCheck className="w-4 h-4 text-emerald-600" />Rules the optimizer enforces</span>}
                    subtitle="Extracted from the documents above; each one is checked against its source quote" />
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 text-slate-500"><tr>
              <th className="text-left font-medium px-4 py-2">Rule</th><th className="text-left font-medium px-2">Value</th>
              <th className="text-left font-medium px-2">Applies to</th><th className="text-left font-medium px-2">Type</th>
              <th className="text-left font-medium px-4">Source</th></tr></thead>
            <tbody>{data.constraints.map((c, i) => (
              <tr key={i} className="border-t border-slate-100 align-top">
                <td className="px-4 py-2 font-medium">{config?.constraintLabels?.[c.type] ?? titleCase(c.type)}</td>
                <td className="px-2 tabular-nums">{String(c.value)}{c.unit ? ` ${c.unit}` : ''}</td>
                <td className="px-2 text-slate-600">{c.scope}</td>
                <td className="px-2"><span className={c.severity === 'hard' ? 'text-rose-600' : 'text-slate-500'}>{c.severity === 'hard' ? 'Must' : 'Prefer'}</span></td>
                <td className="px-4 text-slate-600"><p>{c.source}</p><p className="italic text-slate-400 mt-0.5">“{c.quote}”</p></td>
              </tr>))}
            </tbody>
          </table>
        </div>
        {(data.conflicts.length > 0 || data.unsupported.length > 0) && (
          <div className="px-4 py-3 border-t border-slate-100 text-xs space-y-1">
            {data.conflicts.map((c, i) => <p key={i} className="text-amber-700 flex gap-1.5"><AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />{c}</p>)}
            {data.unsupported.map((u, i) => <p key={`u${i}`} className="text-slate-500">Not enforced automatically: {u}</p>)}
          </div>
        )}
      </Card>
    </div>
  );
}
