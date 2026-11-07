import { createContext, useContext, useState, useCallback } from "react";
import { Icon } from "./icons.jsx";

const ToastCtx = createContext(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  // `options`: { duration (ms), action: { label, onClick } }.
  const push = useCallback((message, tone = "ok", options = {}) => {
    const id = Math.random().toString(36).slice(2);
    const actions = [...(options.actions || []), ...(options.action ? [options.action] : [])];
    setToasts((t) => [...t, { id, message, tone, actions }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), options.duration ?? 3200);
  }, []);

  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toast-wrap">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.tone}`}>
            {t.tone === "ok" ? (
              <Icon.check size={16} />
            ) : (
              <Icon.warn size={16} />
            )}
            <span>{t.message}</span>
            {t.actions.map((a) => (
              <button
                key={a.label}
                type="button"
                className="btn btn-sm toast-action"
                onClick={() => {
                  setToasts((list) => list.filter((x) => x.id !== t.id));
                  a.onClick();
                }}
              >
                {a.label}
              </button>
            ))}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
