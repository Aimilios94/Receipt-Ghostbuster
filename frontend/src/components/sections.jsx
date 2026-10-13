// Reusable content blocks shared between the Dashboard previews and the
// dedicated pages, so the two never drift apart.
import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Icon } from "./icons.jsx";
import { Button, Badge, StatusBadge } from "./ui.jsx";
import { api } from "../lib/api.js";
import { money, shortDate, pct, sourceLabel, confPct, CATEGORY_COLORS, vatByRateLines } from "../lib/format.js";

/* ---------- Spending by category ---------- */
export function CategoryBars({ byCategory, total, limit, onPick }) {
  const rows = Object.entries(byCategory || {}).sort((a, b) => b[1] - a[1]);
  const max = rows.length ? rows[0][1] : 0;
  const shown = limit ? rows.slice(0, limit) : rows;
  if (!rows.length) return <div className="empty">No spending recorded yet.</div>;
  const clickable = typeof onPick === "function";
  return (
    <div>
      {shown.map(([name, amt], i) => (
        <div
          className={`catrow${clickable ? " catrow-click" : ""}`}
          key={name}
          {...(clickable
            ? {
                role: "button",
                tabIndex: 0,
                title: `See ${name} expenses`,
                onClick: (e) => {
                  e.stopPropagation(); // don't also trigger the card's "see all"
                  onPick(name);
                },
                onKeyDown: (e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    e.stopPropagation();
                    onPick(name);
                  }
                },
              }
            : {})}
        >
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

const VAT_RATE_OPTIONS = ["", "6", "13", "23", "0"];

// Reusable multi-rate VAT editor (used in the review queue + the Ledger edit modal).
// `lines` is [{description, amount, vat_rate}]; all VAT lives here (there is no
// separate single VAT field anymore). VAT is summed PER RATE for the live preview.
export function VatLinesEditor({ lines, setLines, busy }) {
  const setLine = (i, k) => (e) =>
    setLines((ls) => ls.map((l, idx) => (idx === i ? { ...l, [k]: e.target.value } : l)));
  const addLine = () => setLines((ls) => [...ls, { description: "", amount: "", vat_rate: "23" }]);
  const removeLine = (i) => setLines((ls) => ls.filter((_, idx) => idx !== i));

  const validLines = lines.filter((l) => Number(l.amount) > 0);
  const linesTotal = Math.round(validLines.reduce((s, l) => s + Number(l.amount || 0), 0) * 100) / 100;
  const breakdown = vatByRateLines(validLines);
  const totalVat = Math.round(breakdown.reduce((s, r) => s + r.vat, 0) * 100) / 100;

  return (
    <div className="vat-lines">
      <div className="vat-lines-head">
        <label style={{ margin: 0 }}>VAT lines{validLines.length ? ` · ${validLines.length}` : ""}</label>
        <button type="button" className="btn btn-sm btn-ghost" onClick={addLine} disabled={busy}>
          <Icon.plus size={13} /> Add VAT line
        </button>
      </div>
      {lines.length ? (
        <>
          {lines.map((l, i) => (
            <div className="vat-line-row" key={i}>
              <input
                className="input"
                placeholder="Item (optional)"
                value={l.description}
                onChange={setLine(i, "description")}
              />
              <input
                className="input num"
                placeholder="€ gross"
                value={l.amount}
                onChange={setLine(i, "amount")}
                inputMode="decimal"
                style={{ maxWidth: 92 }}
              />
              <select className="select" value={l.vat_rate ?? ""} onChange={setLine(i, "vat_rate")} style={{ maxWidth: 92 }}>
                {VAT_RATE_OPTIONS.map((r) => (
                  <option key={r || "none"} value={r}>{r === "" ? "VAT?" : `${r}%`}</option>
                ))}
              </select>
              <button
                type="button"
                className="x-btn"
                aria-label="Remove line"
                title="Remove line"
                onClick={() => removeLine(i)}
              >
                <Icon.x size={14} />
              </button>
            </div>
          ))}
          {validLines.length ? (
            <div className="vat-lines-sum">
              <div className="vat-rates">
                {breakdown.map((r) => (
                  <span className="vat-rate-chip" key={r.label}>
                    <span className="vat-rate-pct">{r.label}</span>
                    <span className="num">{money(r.vat)}</span>
                  </span>
                ))}
              </div>
              <span className="num" style={{ fontSize: 12, color: "var(--text-muted)" }}>
                Total {money(linesTotal)} · VAT {money(totalVat)}
              </span>
            </div>
          ) : null}
        </>
      ) : (
        <p className="vat-lines-hint">
          <b>Add a VAT line</b> for each rate on the receipt (e.g. 6% + 13% + 23%). The amount is the
          sum of the lines, and VAT is summed per rate in code.
        </p>
      )}
    </div>
  );
}

// Seed the VAT-lines editor from an expense: its stored line items if any, else a
// single line for its amount + rate (so single-rate receipts start with one row).
export function seedLines(expense, items) {
  if (items && items.length) {
    return items.map((li) => ({
      description: li.description || "",
      amount: li.amount ?? "",
      vat_rate: li.vat_rate == null ? "" : String(li.vat_rate),
    }));
  }
  if (expense.amount != null) {
    return [
      {
        description: "",
        amount: expense.amount,
        vat_rate: expense.vat_rate == null ? "" : String(expense.vat_rate),
      },
    ];
  }
  return [];
}

function ReviewEditForm({ expense, onSave, onCancel, busy }) {
  const { data: categories } = useQuery({ queryKey: ["categories"], queryFn: api.categories });
  const [showReceipt, setShowReceipt] = useState(false);
  const [form, setForm] = useState({
    vendor: expense.vendor || "",
    expense_date: (expense.expense_date || "").slice(0, 10),
    category: expense.category || "",
  });
  const [lines, setLines] = useState(() => seedLines(expense, null));
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  // Replace the seed with the extractor's stored line items once they load.
  useEffect(() => {
    let active = true;
    api
      .expenseLineItems(expense.id)
      .then((res) => {
        if (active && res.line_items?.length) setLines(seedLines(expense, res.line_items));
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [expense.id]);

  const validLines = lines.filter((l) => Number(l.amount) > 0);
  const linesTotal = Math.round(validLines.reduce((s, l) => s + Number(l.amount || 0), 0) * 100) / 100;

  const save = () => {
    const patch = { expense_date: form.expense_date, amount: linesTotal };
    if (form.vendor) patch.vendor = form.vendor;
    if (form.category) patch.category = form.category;
    patch.line_items = validLines.map((l) => ({
      description: l.description || null,
      amount: Number(l.amount),
      vat_rate: l.vat_rate === "" || l.vat_rate == null ? null : Number(l.vat_rate),
    }));
    onSave(patch);
  };

  return (
    <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 10 }}>
      {expense.receipt_image_url ? (
        <div>
          <Button size="sm" variant="ghost" onClick={() => setShowReceipt(true)}>
            <Icon.receipt size={13} /> View receipt
          </Button>
        </div>
      ) : null}
      <div className="field-row">
        <div className="field">
          <label>Vendor</label>
          <input className="input" value={form.vendor} onChange={set("vendor")} />
        </div>
        <div className="field" style={{ maxWidth: 120 }}>
          <label>Amount (€)</label>
          <input
            className="input num"
            value={linesTotal}
            disabled
            title="Sum of the VAT lines below"
          />
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

      <VatLinesEditor lines={lines} setLines={setLines} busy={busy} />

      <div className="litem-actions">
        <Button size="sm" variant="ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button size="sm" variant="primary" onClick={save} disabled={busy || linesTotal <= 0}>
          Post
        </Button>
      </div>

      {showReceipt ? (
        <div className="overlay receipt-lightbox" onMouseDown={() => setShowReceipt(false)}>
          <img src={expense.receipt_image_url} alt="Receipt" onMouseDown={(e) => e.stopPropagation()} />
        </div>
      ) : null}
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
      <Link to={type === "duplicates" ? "/ledger?view=duplicates" : "/ledger"} className="btn btn-sm">
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
const STATUS_CHOICES = [
  { value: "posted", label: "Posted" },
  { value: "pending_review", label: "Needs review" },
  { value: "confirmed", label: "Confirmed" },
];

export function LedgerTable({ expenses, onDelete, busyId, duplicateIds, onRowClick, onStatusChange }) {
  const [lightbox, setLightbox] = useState(null);
  if (!expenses?.length) return <div className="empty">No entries yet. Add an expense to get started.</div>;
  const clickable = typeof onRowClick === "function";
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
            <th>Receipt</th>
            {onDelete ? <th></th> : null}
          </tr>
        </thead>
        <tbody>
          {expenses.map((e) => {
            const isDup = duplicateIds?.has(e.id);
            return (
            <tr
              key={e.id}
              className={`${isDup ? "row-dup" : ""}${clickable ? " row-click" : ""}`.trim() || undefined}
              {...(clickable
                ? {
                    role: "button",
                    tabIndex: 0,
                    title: "See VAT breakdown and line items",
                    onClick: () => onRowClick(e),
                    onKeyDown: (ev) => {
                      if (ev.key === "Enter" || ev.key === " ") {
                        ev.preventDefault();
                        onRowClick(e);
                      }
                    },
                  }
                : {})}
            >
              <td className="cell-date">{shortDate(e.expense_date)}</td>
              <td className="cell-vendor">{e.vendor || "—"}</td>
              <td className="cell-muted">{e.category || "Uncategorized"}</td>
              <td className="cell-muted">
                {e.source === "card" ? "Card ending 4821" : sourceLabel(e.source)}
              </td>
              <td className="right num">{money(e.amount)}</td>
              <td className="right num cell-muted">{e.vat_amount != null ? money(e.vat_amount) : "—"}</td>
              <td>
                <span style={{ display: "inline-flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
                  {onStatusChange ? (
                    <select
                      className="status-select"
                      value={e.status}
                      title="Change status"
                      onClick={(ev) => ev.stopPropagation()}
                      onChange={(ev) => {
                        ev.stopPropagation();
                        onStatusChange(e, ev.target.value);
                      }}
                      disabled={busyId === e.id}
                    >
                      {STATUS_CHOICES.map((s) => (
                        <option key={s.value} value={s.value}>{s.label}</option>
                      ))}
                    </select>
                  ) : (
                    <StatusBadge expense={e} />
                  )}
                  {isDup ? (
                    <Badge tone="amber" icon={<Icon.warn size={12} />}>Possible duplicate</Badge>
                  ) : null}
                </span>
              </td>
              <td>
                {e.receipt_image_url ? (
                  <button
                    type="button"
                    className="receipt-thumb"
                    title="View receipt"
                    aria-label={`View ${e.vendor || "receipt"} image`}
                    onClick={(ev) => {
                      ev.stopPropagation();
                      setLightbox(e.receipt_image_url);
                    }}
                  >
                    <img src={e.receipt_image_url} alt="" />
                  </button>
                ) : (
                  <span className="cell-muted">—</span>
                )}
              </td>
              {onDelete ? (
                <td className="right">
                  <button
                    className="x-btn"
                    title="Delete entry"
                    aria-label={`Delete ${e.vendor || "entry"}`}
                    onClick={(ev) => {
                      ev.stopPropagation();
                      onDelete(e);
                    }}
                    disabled={busyId === e.id}
                  >
                    <Icon.x size={15} />
                  </button>
                </td>
              ) : null}
            </tr>
            );
          })}
        </tbody>
      </table>

      {lightbox ? (
        <div className="overlay receipt-lightbox" onMouseDown={() => setLightbox(null)}>
          <img src={lightbox} alt="Receipt" onMouseDown={(ev) => ev.stopPropagation()} />
        </div>
      ) : null}
    </div>
  );
}
