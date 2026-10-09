// Constraint Center: every hard rule and soft objective the optimizer uses, editable, importable and testable.
import { useState } from 'react';
import { api, errorMessage } from '../api/client';
import type { ConstraintImport, ConstraintRow, ConstraintTest } from '../api/types';
import { Button } from '../components/common/Button';
import { Card, CardBody, CardHeader } from '../components/common/Card';
import { ErrorState, Spinner, useAsync } from '../components/common/States';
import { Chip, FileDrop, Notice, PageHeader } from '../components/common/ui';
import { Cpu, Download, FlaskConical, Lock, Trash2 } from '../components/common/icons';
import { titleCase } from '../lib/format';
import { useToast } from '../lib/toast';

export function ConstraintCenter({ refreshKey, onChanged }: { refreshKey: number; onChanged: () => void }) {
  const toast = useToast();
  const { data, loading, error, reload } = useAsync(() => api.constraints(), [refreshKey]);
  const [test, setTest] = useState<ConstraintTest | null>(null);
  const [imp, setImp] = useState<{ file: File; res: ConstraintImport } | null>(null);
  const [busy, setBusy] = useState(false);

  async function update(r: ConstraintRow, b: { value?: number; weight?: number; enabled?: boolean }) {
    try { await api.updateConstraint(r.constraint_id, b); toast(`${r.constraint_id} updated.`); reload(); onChanged(); }
    catch (e) { toast(errorMessage(e), 'error'); }
  }
  async function runTest() {
    setBusy(true);
    try { setTest(await api.testConstraints()); } catch (e) { toast(errorMessage(e), 'error'); } finally { setBusy(false); }
  }
  async function preview(f: File) {
    try { setImp({ file: f, res: await api.importConstraints(f, false) }); } catch (e) { toast(errorMessage(e), 'error'); }
  }
  async function apply() {
    if (!imp) return;
    try { const r = await api.importConstraints(imp.file, true); toast(`${r.valid.length} rule(s) applied.`); setImp(null); reload(); onChanged(); }
    catch (e) { toast(errorMessage(e), 'error'); }
  }
  async function remove(id: string) {
    try { await api.removeConstraint(id); toast(`${id} removed.`); reload(); } catch (e) { toast(errorMessage(e), 'error'); }
  }

  if (loading && !data) return <Spinner />;
  if (error || !data) return <ErrorState message={error ?? 'Unable to load constraints.'} onRetry={reload} />;
  const hard = data.constraints.filter((r) => r.type === 'HARD');
  const soft = data.constraints.filter((r) => r.type === 'SOFT');
  const result = (id: string) => test?.results.find((x) => x.constraint_id === id);
  return (
    <div className="space-y-4">
      <PageHeader title="Constraint Center"
                  subtitle="Hard constraints are never violated: a candidate who breaks one is rejected, not ranked. Soft constraints only rank people who pass every hard rule."
                  actions={<>
                    <Button size="sm" icon={<FlaskConical className="w-3.5 h-3.5" />} disabled={busy} onClick={runTest}>{busy ? 'Testing…' : 'Test against schedule'}</Button>
                    <Button size="sm" icon={<Download className="w-3.5 h-3.5" />} onClick={() => api.downloadTemplate('constraints.csv').catch((e) => toast(errorMessage(e), 'error'))}>CSV template</Button>
                    <Button size="sm" icon={<Download className="w-3.5 h-3.5" />} onClick={() => api.downloadTemplate('constraints.json').catch((e) => toast(errorMessage(e), 'error'))}>JSON template</Button>
                  </>} />
      <Notice tone={data.solver.cp_sat ? 'success' : 'warning'}>
        <span className="inline-flex items-center gap-1.5 font-semibold"><Cpu className="w-3.5 h-3.5" />Optimizer: {data.solver.engine}</span>{' '}{data.solver.message}
        {data.solver.self_test && <> Self-test: {data.solver.self_test.status} in {data.solver.self_test.ms} ms.</>}
      </Notice>
      {test && <Notice tone={test.summary.fail ? 'warning' : 'success'}>Checked {test.assignments} assignments: {test.summary.pass} rule(s) pass, {test.summary.fail} with violations in the current schedule.</Notice>}
      <Card>
        <CardHeader title={`Hard constraints (${hard.length})`} subtitle="Must never be violated" />
        <RuleTable rows={hard} result={result} onUpdate={update} onRemove={remove} />
      </Card>
      <Card>
        <CardHeader title={`Soft constraints (${soft.length})`} subtitle="Weights (0–100+) change how repairs are ranked" />
        <RuleTable rows={soft} result={result} onUpdate={update} onRemove={remove} />
      </Card>
      <Card>
        <CardHeader title="Import constraints" subtitle="CSV: constraint_id,type,category,rule,priority,weight,enabled[,value][,scope] · JSON for scoped rules" />
        <CardBody className="p-4 space-y-3">
          <FileDrop accept=".csv,.json" onFile={preview} label="Choose a CSV or JSON file" />
          {imp && (
            <div className="space-y-2 text-xs">
              {imp.res.errors.length > 0 && <Notice tone="error"><ul>{imp.res.errors.map((e) => <li key={e}>{e}</li>)}</ul></Notice>}
              {imp.res.unenforced.length > 0 && <Notice tone="warning">No engine model for {imp.res.unenforced.join(', ')}: they will be stored and shown, but not enforced.</Notice>}
              <p>{imp.res.valid.length} valid rule(s): {imp.res.valid.map((r) => r.constraint_id).join(', ')}</p>
              <Button variant="primary" disabled={!!imp.res.errors.length || !imp.res.valid.length} onClick={apply}>Apply {imp.res.valid.length} rule(s)</Button>
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

function RuleTable({ rows, result, onUpdate, onRemove }: {
  rows: ConstraintRow[]; result: (id: string) => ConstraintTest['results'][number] | undefined;
  onUpdate: (r: ConstraintRow, b: { value?: number; weight?: number; enabled?: boolean }) => void; onRemove: (id: string) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs text-left">
        <thead className="text-[11px] uppercase text-slate-500 bg-slate-50"><tr><th className="px-3 py-2">ID</th><th className="px-2">Rule</th><th className="px-2">Category</th><th className="px-2">Value / weight</th><th className="px-2">Enabled</th><th className="px-2">Test</th><th /></tr></thead>
        <tbody>
          {rows.map((r) => {
            const t = result(r.constraint_id);
            return (
              <tr key={r.constraint_id} className={`border-t border-slate-100 ${r.enabled ? '' : 'opacity-60'}`}>
                <td className="px-3 py-2 font-mono">{r.constraint_id}</td>
                <td className="px-2">{r.rule}{!r.enforced && <Chip tone="amber" className="ml-1">not enforced</Chip>}{r.scope && <span className="text-slate-500"> · {Object.entries(r.scope).map(([k, v]) => `${k}: ${v}`).join(', ')}</span>}</td>
                <td className="px-2">{titleCase(r.category)}</td>
                <td className="px-2 whitespace-nowrap">
                  {r.type === 'SOFT'
                    ? <NumberEdit value={r.weight} label={`${r.constraint_id} weight`} onSave={(v) => onUpdate(r, { weight: v })} suffix="weight" />
                    : typeof r.value === 'number' ? <NumberEdit value={r.value} label={`${r.constraint_id} value`} onSave={(v) => onUpdate(r, { value: v })} suffix={r.unit ?? ''} />
                      : Array.isArray(r.value) ? r.value.join(', ') : '—'}
                  {r.category === 'fairness' && typeof r.value === 'number' && <span className="text-slate-500"> · window {r.value} days</span>}
                </td>
                <td className="px-2">
                  {r.locked ? <span className="inline-flex items-center gap-1 text-slate-500" title="Core safety rule"><Lock className="w-3 h-3" />always</span> : (
                    <label className="inline-flex items-center gap-1.5 cursor-pointer">
                      <input type="checkbox" checked={r.enabled} aria-label={`Enable ${r.constraint_id}`} onChange={(e) => onUpdate(r, { enabled: e.target.checked })} />
                      {r.enabled ? 'on' : 'off'}
                    </label>)}
                </td>
                <td className="px-2">{t ? <Chip tone={t.status === 'pass' ? 'green' : t.status === 'fail' ? 'red' : 'slate'}>{t.status}{t.violations ? ` · ${t.violations}` : ''}</Chip> : '—'}</td>
                <td className="px-2 text-right">{r.source === 'imported' && <Button size="sm" variant="ghost" aria-label={`Remove ${r.constraint_id}`} icon={<Trash2 className="w-3.5 h-3.5" />} onClick={() => onRemove(r.constraint_id)}>Remove</Button>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function NumberEdit({ value, onSave, label, suffix }: { value: number; onSave: (v: number) => void; label: string; suffix: string }) {
  const [v, setV] = useState(String(value));
  const changed = v !== String(value) && v.trim() !== '' && !Number.isNaN(Number(v));
  return (
    <span className="inline-flex items-center gap-1">
      <input aria-label={label} className="input w-20" inputMode="decimal" value={v} onChange={(e) => setV(e.target.value)} />
      <span className="text-slate-500">{suffix}</span>
      {changed && <Button size="sm" onClick={() => onSave(Number(v))}>Save</Button>}
    </span>
  );
}
