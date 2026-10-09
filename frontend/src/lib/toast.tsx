import React, { createContext, useCallback, useContext, useState } from 'react';
import { CheckCircle2, AlertTriangle, Info, XCircle, X } from '../components/common/icons';

type Tone = 'success' | 'error' | 'info' | 'warning';
interface Toast { id: number; tone: Tone; message: string }

const Ctx = createContext<(message: string, tone?: Tone) => void>(() => {});

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((message: string, tone: Tone = 'success') => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, tone, message }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === 'error' ? 7000 : 4000);
  }, []);
  const icon = { success: CheckCircle2, error: XCircle, info: Info, warning: AlertTriangle };
  const color = {
    success: 'border-emerald-200 text-emerald-800', error: 'border-rose-200 text-rose-800',
    info: 'border-blue-200 text-blue-800', warning: 'border-amber-200 text-amber-800',
  };
  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="fixed bottom-4 right-4 z-[60] flex flex-col gap-2 w-80" role="status" aria-live="polite">
        {toasts.map((t) => {
          const Icon = icon[t.tone];
          return (
            <div key={t.id} className={`bg-white border ${color[t.tone]} rounded-lg shadow-lg px-3 py-2.5 flex items-start gap-2 text-xs`}>
              <Icon className="w-4 h-4 shrink-0 mt-0.5" />
              <span className="flex-1 text-slate-800">{t.message}</span>
              <button aria-label="Dismiss" className="text-slate-400 hover:text-slate-700" onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))}>
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          );
        })}
      </div>
    </Ctx.Provider>
  );
}

export const useToast = () => useContext(Ctx);
