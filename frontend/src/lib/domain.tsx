// Domain adaptivity: every label, KPI and sub-dashboard comes from shared/domains/<domain>.json.
import React, { createContext, useContext } from 'react';
import type { DomainConfig } from '../api/types';

interface DomainCtx {
  config: DomainConfig | null;
  /** Domain terminology, e.g. t('employee') → 'Staff member' (healthcare) / 'Operator' (manufacturing). */
  t: (key: string, fallback?: string) => string;
}

const Ctx = createContext<DomainCtx>({ config: null, t: (_k, f) => f ?? _k });

export function DomainProvider({ config, children }: { config: DomainConfig | null; children: React.ReactNode }) {
  const t = (key: string, fallback?: string) => config?.terminology?.[key] ?? fallback ?? key;
  return (
    <Ctx.Provider value={{ config, t }}>
      <div style={{ '--accent': config?.accent ?? '#2563eb' } as React.CSSProperties} data-identity={config?.identity ?? 'default'}>
        {children}
      </div>
    </Ctx.Provider>
  );
}

export const useDomain = () => useContext(Ctx);
