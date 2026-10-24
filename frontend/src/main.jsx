import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as Sentry from "@sentry/react";
import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import App from "./App.jsx";
import "./styles/index.css";

// Opt-in browser error tracking. No-op unless VITE_SENTRY_DSN is set (git-ignored
// .env), so the app runs with no external dependency. Errors only — no performance
// tracing (tracesSampleRate 0) — to stay inside Sentry's free tier. See docs/MONITORING.md.
if (import.meta.env.VITE_SENTRY_DSN) {
  Sentry.init({
    dsn: import.meta.env.VITE_SENTRY_DSN,
    environment: import.meta.env.VITE_SENTRY_ENVIRONMENT || "local",
    tracesSampleRate: 0,
    sendDefaultPii: false,
  });
}

const queryClient = new QueryClient({
  defaultOptions: {
    // retry a couple of times: a heavy write (reconcile) can briefly overlap with
    // refetches and cause a transient server socket blip that recovers on retry.
    queries: { refetchOnWindowFocus: false, retry: 2, retryDelay: 400, staleTime: 15_000 },
  },
});

// A quiet, self-contained fallback if a render throws — the error is reported to
// Sentry (when enabled) and the user gets a reload affordance instead of a blank page.
function AppCrashFallback() {
  return (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: "2rem",
      font: "15px/1.5 'Geist Variable', system-ui, sans-serif", color: "#e5e7eb", background: "#0b0f17" }}>
      <div style={{ maxWidth: 420, textAlign: "center" }}>
        <div style={{ fontSize: "1.6rem", marginBottom: ".5rem" }}>👻 Something went wrong</div>
        <p style={{ color: "#9ca3af", margin: "0 0 1.25rem" }}>
          The page hit an unexpected error. It’s been logged — reloading usually fixes it.
        </p>
        <button onClick={() => window.location.reload()}
          style={{ padding: ".55rem 1.1rem", borderRadius: 8, border: "1px solid #374151",
            background: "#111827", color: "#e5e7eb", cursor: "pointer" }}>
          Reload
        </button>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <Sentry.ErrorBoundary fallback={<AppCrashFallback />}>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </Sentry.ErrorBoundary>
  </React.StrictMode>
);
