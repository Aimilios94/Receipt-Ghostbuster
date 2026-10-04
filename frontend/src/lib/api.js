// Thin client over the FastAPI backend. All responses are wrapped
// ({ expenses: [...] }, { expense: {...} }); callers unwrap as needed.
//
// Auth: in demo mode the backend uses DEV_USER_ID and needs no header.
// If a Supabase JWT is ever wired client-side, set it via setToken().

const BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

let authToken = null;
export function setToken(t) {
  authToken = t;
}

async function request(path, { method = "GET", body, form, signal } = {}) {
  const headers = {};
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;

  let payload;
  if (form) {
    payload = form; // FormData — let the browser set the boundary
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  let res;
  try {
    res = await fetch(`${BASE}${path}`, { method, headers, body: payload, signal });
  } catch (e) {
    throw new ApiError(
      `Can't reach the backend at ${BASE}. Is it running? (uvicorn app.main:app)`,
      0
    );
  }

  if (!res.ok) {
    let detail;
    try {
      const j = await res.json();
      detail = j.detail || j.message;
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(detail || `${res.status} ${res.statusText}`, res.status);
  }
  if (res.status === 204) return null;
  return res.json();
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

export const api = {
  health: () => request("/health"),

  // ----- expenses / ledger -----
  listExpenses: (status) =>
    request(`/expenses${status ? `?status=${encodeURIComponent(status)}` : ""}`).then(
      (r) => r.expenses
    ),
  createExpense: (data) => request("/expenses", { method: "POST", body: data }).then((r) => r.expense),

  // ----- review queue -----
  reviewQueue: () => request("/expenses/review-queue").then((r) => r.expenses),
  confirmExpense: (id, patch) =>
    request(`/expenses/${id}/confirm`, { method: "POST", body: patch || {} }).then(
      (r) => r.expense
    ),

  // ----- receipt extraction -----
  extract: (file, source = "card") => {
    const form = new FormData();
    form.append("file", file);
    form.append("source", source);
    return request("/extract", { method: "POST", form });
  },

  // ----- bank import -----
  importBank: (file, mapping) => {
    const form = new FormData();
    form.append("file", file);
    if (mapping) form.append("mapping", JSON.stringify(mapping));
    return request("/bank/import", { method: "POST", form });
  },

  // ----- reconcile / exceptions / close -----
  reconcile: () => request("/reconcile", { method: "POST" }),
  exceptions: (month) => request(`/exceptions${month ? `?month=${month}` : ""}`),
  close: (month) => request(`/close${month ? `?month=${month}` : ""}`),

  // ----- categories -----
  categories: () => request("/categories").then((r) => r.categories),

  // ----- subscriptions (Phase 2 — Refund Hunter) -----
  detectSubscriptions: () => request("/subscriptions/detect", { method: "POST" }),
  listSubscriptions: () => request("/subscriptions").then((r) => r.subscriptions),
  updateSubscription: (id, patch) =>
    request(`/subscriptions/${id}`, { method: "POST", body: patch }).then((r) => r.subscription),
  draftRefundEmail: (id, action = "cancel") =>
    request(`/subscriptions/${id}/draft-email`, { method: "POST", body: { action } }).then(
      (r) => r.refund_action
    ),
  listRefundActions: () => request("/refund-actions").then((r) => r.refund_actions),
  updateRefundAction: (id, patch) =>
    request(`/refund-actions/${id}`, { method: "POST", body: patch }).then((r) => r.refund_action),
};
