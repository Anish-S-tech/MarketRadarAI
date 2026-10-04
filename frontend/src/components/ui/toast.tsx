import { Bell, X } from "lucide-react";
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { PriorityBadge } from "./badges";

interface Toast {
  id: number;
  title: string;
  body?: string;
  priority?: string;
  href?: string;
}

const ToastContext = createContext<(t: Omit<Toast, "id">) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const dismiss = (id: number) => setToasts((ts) => ts.filter((t) => t.id !== id));
  const push = useCallback((t: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setToasts((ts) => [...ts.slice(-3), { ...t, id }]);
    setTimeout(() => setToasts((ts) => ts.filter((x) => x.id !== id)), 9000);
  }, []);

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className="bg-surface pointer-events-auto rounded-xl border border-default p-3.5 shadow-lg">
            <div className="flex items-start gap-2.5">
              <Bell className="mt-0.5 size-4 shrink-0 text-brand-600" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  {t.priority && <PriorityBadge priority={t.priority} />}
                  <span className="text-xs text-subtle">New alert</span>
                </div>
                {t.href ? (
                  <Link to={t.href} onClick={() => dismiss(t.id)} className="mt-1 block text-sm font-medium hover:underline">
                    {t.title}
                  </Link>
                ) : (
                  <p className="mt-1 text-sm font-medium">{t.title}</p>
                )}
                {t.body && <p className="mt-0.5 text-xs text-muted">{t.body}</p>}
              </div>
              <button onClick={() => dismiss(t.id)} className="text-subtle hover:text-default" aria-label="Dismiss">
                <X className="size-4" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
