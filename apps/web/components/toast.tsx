"use client";

import { AlertTriangle, CircleCheck, CircleX, X } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

type Toast = { id: number; message: string; type: "success" | "warning" | "error" };
type ToastContextValue = {
  notify: (message: string, type?: Toast["type"]) => void;
};
const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const notify = useCallback(
    (message: string, type: Toast["type"] = "success") => {
      const id = Date.now() + Math.random();
      setToasts((items) => [...items, { id, message, type }]);
      window.setTimeout(
        () => setToasts((items) => items.filter((item) => item.id !== id)),
        4500,
      );
    },
    [],
  );
  const value = useMemo(() => ({ notify }), [notify]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        className="fixed right-4 bottom-4 z-[100] grid w-[min(24rem,calc(100vw-2rem))] gap-2"
        aria-live="polite"
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`flex items-center gap-3 rounded-xl border p-3 shadow-2xl backdrop-blur ${
            toast.type === "error"
              ? "border-rose-700/60 bg-rose-950/95 text-rose-100"
              : toast.type === "warning"
                ? "border-amber-700/60 bg-amber-950/95 text-amber-100"
                : "border-emerald-700/60 bg-emerald-950/95 text-emerald-100"
          }`}
          >
            {toast.type === "error" ? (
              <CircleX size={18} />
            ) : toast.type === "warning" ? (
              <AlertTriangle size={18} />
            ) : (
              <CircleCheck size={18} />
            )}
            <p className="min-w-0 flex-1 text-sm">{toast.message}</p>
            <button
              aria-label="关闭提示"
              onClick={() =>
                setToasts((items) =>
                  items.filter((item) => item.id !== toast.id),
                )
              }
            >
              <X size={16} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const value = useContext(ToastContext);
  if (!value) throw new Error("useToast must be used inside ToastProvider");
  return value;
}
