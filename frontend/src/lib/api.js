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
  // No patch -> send no body (confirm posts as-is). With a patch, it must carry a
  // valid amount (ExpenseCreate requires amount > 0).
  confirmExpense: (id, patch) =>
    request(`/expenses/${id}/confirm`, patch ? { method: "POST", body: patch } : { method: "POST" }).then(
      (r) => r.expense
    ),
  deleteExpense: (id) => request(`/expenses/${id}`, { method: "DELETE" }),
  setExpenseStatus: (id, status) =>
    request(`/expenses/${id}/status`, { method: "POST", body: { status } }).then((r) => r.expense),
  setExpenseCategory: (id, category) =>
    request(`/expenses/${id}/category`, { method: "POST", body: { category } }).then((r) => r.expense),
  // Per-line VAT: all line items (joined to the ledger client-side), or one receipt's.
  lineItems: () => request("/expenses/line-items").then((r) => r.line_items),
  expenseLineItems: (id) => request(`/expenses/${id}/line-items`),

  // Replace an existing expense's receipt photo and re-read it.
  rescanReceipt: (id, file) => {
    const form = new FormData();
    form.append("file", file);
    return request(`/expenses/${id}/rescan`, { method: "POST", form });
  },

  // ----- receipt extraction -----
  extract: (file, source = "card", note) => {
    const form = new FormData();
    form.append("file", file);
    form.append("source", source);
    if (note && note.trim()) form.append("note", note.trim());
    return request("/extract", { method: "POST", form });
  },

  // ----- bank import -----
  importBank: (file, mapping, note) => {
    const form = new FormData();
    form.append("file", file);
    if (mapping) form.append("mapping", JSON.stringify(mapping));
    if (note && note.trim()) form.append("note", note.trim());
    return request("/bank/import", { method: "POST", form });
  },
  // Imported statement files (one row per upload), with a live needs-receipt count.
  listStatements: () => request("/bank/statements").then((r) => r.statements),
  statementTransactions: (id) => request(`/bank/statements/${id}/transactions`),
  deleteStatement: (id) => request(`/bank/statements/${id}`, { method: "DELETE" }),

  // ----- reconcile / exceptions / close -----
  reconcile: () => request("/reconcile", { method: "POST" }),
  reconcileState: () => request("/reconcile/state"),
  matchExpense: (expenseId, transactionId) =>
    request("/reconcile/match", { method: "POST", body: { expense_id: expenseId, transaction_id: transactionId } }),
  unmatchExpense: (expenseId, transactionId) =>
    request("/reconcile/unmatch", { method: "POST", body: { expense_id: expenseId, transaction_id: transactionId } }),
  markNoReceipt: (transactionId, noReceipt = true) =>
    request("/reconcile/no-receipt", { method: "POST", body: { transaction_id: transactionId, no_receipt: noReceipt } }),
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
  deliverRefundAction: (id) => request(`/refund-actions/${id}/deliver`, { method: "POST" }),
};
