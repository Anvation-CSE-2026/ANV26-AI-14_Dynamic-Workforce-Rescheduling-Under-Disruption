// A domain sub-dashboard (e.g. "Nurse Manager" / "Staffing Coordinator"). Which widgets appear, and in what order,
// comes from shared/domains/<domain>.json → subDashboards[i].widgets. No domain logic lives here.
import React from 'react';
import { api } from '../api/client';
import type { Dashboard as DashboardData } from '../api/types';
import { MetricCard } from '../components/common/MetricCard';
import { EmptyState, ErrorState, Spinner, useAsync } from '../components/common/States';
import { WIDGETS } from '../components/widgets/Widgets';
import { useDomain } from '../lib/domain';
import { fmtKpi } from '../lib/format';

export function SubDashboard({ index, refreshKey }: { index: number; refreshKey: number }) {
  const { config } = useDomain();
  const { loading, error, data, reload } = useAsync<DashboardData>(() => api.dashboard(), [refreshKey]);
  const sub = config?.subDashboards[index];
  if (!sub) return <EmptyState title="Sub-dashboard not configured" />;
  if (loading && !data) return <Spinner />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;
  const kpis = data.kpis.slice(0, 4);
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">{sub.name}</h2>
        <p className="text-xs text-slate-500">{sub.audience}</p>
      </div>
      <section className="grid grid-cols-2 lg:grid-cols-4 gap-3" aria-label="Key indicators">
        {kpis.map((k) => { const f = fmtKpi(k, k.value); return <MetricCard key={k.id} label={k.label} value={f.value} unit={f.unit} subtext={k.hint} />; })}
      </section>
      <div className="grid lg:grid-cols-2 gap-5">
        {sub.widgets.map((w) => {
          const W = WIDGETS[w];
          return W ? <W key={w} data={data.widgets} /> : null;
        })}
      </div>
    </div>
  );
}
