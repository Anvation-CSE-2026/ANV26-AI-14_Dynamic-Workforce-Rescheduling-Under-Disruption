import React from 'react';
import { AlertTriangle, Inbox, Loader2 } from './icons';
import { Button } from './Button';

export const Spinner = ({ label = 'Loading…' }: { label?: string }) => (
  <div className="flex items-center gap-2 text-xs text-slate-500 p-6 justify-center" role="status">
    <Loader2 className="w-4 h-4 animate-spin" /> {label}
  </div>
);

export const EmptyState = ({ title, hint, action }: { title: string; hint?: string; action?: React.ReactNode }) => (
  <div className="flex flex-col items-center text-center gap-2 p-8 text-slate-500">
    <Inbox className="w-6 h-6 text-slate-300" />
    <p className="text-sm font-medium text-slate-700">{title}</p>
    {hint && <p className="text-xs max-w-sm">{hint}</p>}
    {action}
  </div>
);

export const ErrorState = ({ message, onRetry }: { message: string; onRetry?: () => void }) => (
  <div className="flex flex-col items-center text-center gap-2 p-8" role="alert">
    <AlertTriangle className="w-6 h-6 text-rose-400" />
    <p className="text-sm text-rose-700">{message}</p>
    {onRetry && <Button size="sm" onClick={onRetry}>Retry</Button>}
  </div>
);

/** Fetch helper with loading / error / data states. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [state, setState] = React.useState<{ loading: boolean; error?: string; data?: T }>({ loading: true });
  const run = React.useCallback(() => {
    setState((s) => ({ ...s, loading: !s.data, error: undefined }));
    fn().then((data) => setState({ loading: false, data })).catch((e) => setState({ loading: false, error: e.message ?? String(e) }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  React.useEffect(() => { run(); }, [run]);
  return { ...state, reload: run };
}

/** Re-run ``reload`` every ``ms`` while the tab is visible: keeps dashboards in sync with changes made by
 *  other users (requests, approvals) without a websocket. */
export function usePoll(reload: () => void, ms = 10000) {
  React.useEffect(() => {
    const t = setInterval(() => { if (document.visibilityState === 'visible') reload(); }, ms);
    return () => clearInterval(t);
  }, [reload, ms]);
}
