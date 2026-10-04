// Reusable content blocks shared between the Dashboard previews and the
// dedicated pages, so the two never drift apart.
import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Icon } from "./icons.jsx";
import { Button, Badge, StatusBadge } from "./ui.jsx";
import { api } from "../lib/api.js";
import { money, shortDate, pct, sourceLabel, confPct, CATEGORY_COLORS } from "../lib/format.js";

/* ---------- Spending by category ---------- */
export function CategoryBars({ byCategory, total, limit }) {
  const rows = Object.entries(byCategory || {}).sort((a, b) => b[1] - a[1]);
  const max = rows.length ? rows[0][1] : 0;
  const shown = limit ? rows.slice(0, limit) : rows;
  if (!rows.length) return <div className="empty">No spending recorded yet.</div>;
  return (
    <div>
      {shown.map(([name, amt], i) => (
        <div className="catrow" key={name}>
          <span className="name">{name}</span>
          <span className="catbar">
            <span
              style={{
                width: `${Math.max(4, pct(amt, max))}%`,
                background: CATEGORY_COLORS[i % CATEGORY_COLORS.length],
              }}
            />
          </span>
          <span className="amt num">{money(amt)}</span>
          <span className="pct num">{pct(amt, total)}%</span>
        </div>
      ))}
    </div>
  );
}

/* ---------- Review queue item (editable before posting) ---------- */
export function ReviewItem({ expense, onPost, onDiscard, busy }) {
  const [editing, setEditing] = useState(false);
  const c = confPct(expense.confidence);
  const tone = c == null ? "var(--text-dim)" : c >= 70 ? "var(--green)" : c >= 55 ? "var(--amber)" : "var(--red)";

  return (
    <div className="litem">
      <div className="litem-top">
        <div>
          <div className="litem-title">{expense.vendor || "Unreadable vendor"}</div>
          <div className="litem-meta">
            {shortDate(expense.expense_date)} · {sourceLabel(expense.source)}
            {expense.category ? ` · suggested ${expense.category.toLowerCase()}` : ""}
          </div>
        </div>
        <div className="litem-amt num">{money(expense.amount)}</div>
      </div>
      <div className="conf">
        <span className="conf-bar">
          <span style={{ width: `${c ?? 0}%`, background: tone }} />
        </span>
        {c != null ? `${c}% sure` : "confidence unknown"}
        {expense.note ? <span className="conf-note">· {expense.note}</span> : null}
      </div>

      {editing ? (
        <ReviewEditForm
          expense={expense}
          busy={busy}
          onCancel={() => setEditing(false)}
          onSave={(patch) => onPost(expense, patch)}
        />
      ) : (
        <div className="litem-actions">
          <Button size="sm" variant="danger-ghost" onClick={() => onDiscard(expense)} disabled={busy}>
            Discard
          </Button>
          <Button size="sm" onClick={() => setEditing(true)} disabled={busy}>
            Edit
          </Button>
          <Button size="sm" variant="primary" onClick={() => onPost(expense)} disabled={busy}>
            Post
          </Button>
        </div>
      )}
    </div>
  );
}

function ReviewEditForm({ expense, onSave, onCancel, busy }) {
  const { data: categories } = useQuery({ queryKey: ["categories"], queryFn: api.categories });
  const [form, setForm] = useState({
    vendor: expense.vendor || "",
    amount: expense.amount ?? "",
    expense_date: (expense.expense_date || "").slice(0, 10),
    category: expense.category || "",
  });
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const save = () => {
    const patch = { amount: Number(form.amount), expense_date: form.expense_date };
    if (form.vendor) patch.vendor = form.vendor;
    if (form.category) patch.category = form.category;
    onSave(patch);
  };

  return (
    <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 10 }}>
      <div className="field-row">
        <div className="field">
          <label>Vendor</label>
          <input className="input" value={form.vendor} onChange={set("vendor")} />
        </div>
        <div className="field" style={{ maxWidth: 120 }}>
          <label>Amount (€)</label>
          <input className="input num" value={form.amount} onChange={set("amount")} inputMode="decimal" />
        </div>
      </div>
      <div className="field-row">
        <div className="field">
          <label>Date</label>
          <input className="input" type="date" value={form.expense_date} onChange={set("expense_date")} />
        </div>
        <div className="field">
          <label>Category</label>
          <select className="select" value={form.category} onChange={set("category")}>
            <option value="">Auto / keep</option>
            {(categories || []).map((cat) => (
              <option key={cat.id} value={cat.name}>
                {cat.name}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="litem-actions">
        <Button size="sm" variant="ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button size="sm" variant="primary" onClick={save} disabled={busy || !form.amount || Number(form.amount) <= 0}>
          Post
        </Button>
      </div>
    </div>
  );
}

/* ---------- Reconciliation exception item ---------- */
const EXC_META = {
  unmatched_bank: { kind: "No receipt", tone: "" },
  duplicates: { kind: "Possible duplicate", tone: "" },
  amount_mismatch: { kind: "Amount differs", tone: "" },
  missing_vat: { kind: "VAT missing", tone: "" },
  unmatched_expenses: { kind: "No bank match", tone: "red" },
};

export function ExceptionItem({ type, data }) {
  const meta = EXC_META[type] || { kind: type, tone: "" };
  let vendor = "—";
  let detail = "";

  if (type === "unmatched_bank") {
    vendor = "Bank payment with no receipt";
    detail = `${data.description || "Payment"} · ${shortDate(data.txn_date)} · ${money(Math.abs(data.amount))}`;
  } else if (type === "duplicates") {
    const g = data; // array of rows
    vendor = `${g[0]?.vendor || "Vendor"} charged ${g.length}×`;
    detail = `${g.length} × ${money(g[0]?.amount)} on ${shortDate(g[0]?.expense_date)}`;
  } else if (type === "amount_mismatch") {
    vendor = data.expense?.vendor || "Expense";
    detail = `Receipt ${money(data.expense?.amount)} · bank ${money(Math.abs(data.transaction?.amount))}`;
  } else if (type === "missing_vat") {
    vendor = data.vendor || "Expense";
    detail = `The VAT line on the receipt is unreadable · ${money(data.amount)}`;
  } else if (type === "unmatched_expenses") {
    vendor = data.vendor || "Card expense";
    detail = `${sourceLabel(data.source)} · ${shortDate(data.expense_date)} · ${money(data.amount)}`;
  }

  return (
    <div className="exc">
      <span className={`exc-ico ${meta.tone}`}>
        <Icon.warn size={16} />
      </span>
      <div className="exc-body">
        <div className={`exc-kind ${meta.tone}`}>{meta.kind}</div>
        <div className="exc-vendor">{vendor}</div>
        <div className="exc-detail">{detail}</div>
      </div>
      <Link to="/ledger" className="btn btn-sm">
        Resolve
      </Link>
    </div>
  );
}

// Flatten the exceptions payload into a single ordered list of {type, data}.
export function flattenExceptions(exc) {
  if (!exc) return [];
  const out = [];
  const e = exc.exceptions || {};
  (e.unmatched_bank || []).forEach((d) => out.push({ type: "unmatched_bank", data: d }));
  (e.duplicates || []).forEach((d) => out.push({ type: "duplicates", data: d }));
  (e.amount_mismatch || []).forEach((d) => out.push({ type: "amount_mismatch", data: d }));
  (e.missing_vat || []).forEach((d) => out.push({ type: "missing_vat", data: d }));
  (e.unmatched_expenses || []).forEach((d) => out.push({ type: "unmatched_expenses", data: d }));
  return out;
}

/* ---------- Ledger table ---------- */
export function LedgerTable({ expenses, onDelete, busyId }) {
  if (!expenses?.length) return <div className="empty">No entries yet. Add an expense to get started.</div>;
  return (
    <div className="table-wrap">
      <table className="ledger">
        <thead>
          <tr>
            <th>Date</th>
            <th>Vendor</th>
            <th>Category</th>
            <th>Paid with</th>
            <th className="right">Amount</th>
            <th className="right">VAT</th>
            <th>Status</th>
            {onDelete ? <th></th> : null}
          </tr>
        </thead>
        <tbody>
          {expenses.map((e) => (
            <tr key={e.id}>
              <td className="cell-date">{shortDate(e.expense_date)}</td>
              <td className="cell-vendor">{e.vendor || "—"}</td>
              <td className="cell-muted">{e.category || "Uncategorized"}</td>
              <td className="cell-muted">
                {e.source === "card" ? "Card ending 4821" : sourceLabel(e.source)}
              </td>
              <td className="right num">{money(e.amount)}</td>
              <td className="right num cell-muted">{e.vat_amount != null ? money(e.vat_amount) : "—"}</td>
              <td>
                <StatusBadge expense={e} />
              </td>
              {onDelete ? (
                <td className="right">
                  <button
                    className="x-btn"
                    title="Delete entry"
                    aria-label={`Delete ${e.vendor || "entry"}`}
                    onClick={() => onDelete(e)}
                    disabled={busyId === e.id}
                  >
                    <Icon.x size={15} />
                  </button>
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
