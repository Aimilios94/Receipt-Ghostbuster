// Reusable content blocks shared between the Dashboard previews and the
// dedicated pages, so the two never drift apart.
import { useState, useEffect, useRef } from "react";
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
export function ReviewItem({ expense, onPost, onDiscard, onRetake, busy }) {
  const [editing, setEditing] = useState(false);
  const retakeRef = useRef();
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
          {onRetake ? (
            <>
              <input
                ref={retakeRef}
                type="file"
                accept="image/*"
                hidden
                onChange={(ev) => {
                  const f = ev.target.files?.[0];
                  ev.target.value = "";
                  if (f) onRetake(expense, f);
                }}
              />
              <Button
                size="sm"
                variant="ghost"
                onClick={() => retakeRef.current?.click()}
                disabled={busy}
                title="Upload a clearer photo of this receipt to re-read it"
              >
                <Icon.camera size={13} /> Retake
              </Button>
            </>
          ) : null}
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

const VAT_RATE_OPTIONS = ["", "0", "6", "13", "23"];

// Reusable multi-rate VAT editor (used in the review queue + the Ledger edit modal).
// `lines` is [{description, amount, vat_rate}]; all VAT lives here (there is no
// separate single VAT field anymore). VAT is summed PER RATE for the live preview.
const SUGGESTED_TIP =
  "Suggested VAT — no VAT was printed on this receipt, so the rate is estimated from the " +
  "product type (e.g. prepared food 13%, drinks 23%). Confirm it or change it.";

export function VatLinesEditor({ lines, setLines, busy }) {
  const setLine = (i, k) => (e) =>
    setLines((ls) =>
      ls.map((l, idx) =>
        idx === i
          ? { ...l, [k]: e.target.value, ...(k === "vat_rate" ? { suggested: false } : {}) }
          : l
      )
    );
  const addLine = () => setLines((ls) => [...ls, { description: "", amount: "", vat_rate: "23" }]);
  const removeLine = (i) => setLines((ls) => ls.filter((_, idx) => idx !== i));
  const hasSuggested = lines.some((l) => l.suggested);

  const validLines = lines.filter((l) => Number(l.amount) > 0);
  const linesTotal = Math.round(validLines.reduce((s, l) => s + Number(l.amount || 0), 0) * 100) / 100;
  const breakdown = vatByRateLines(validLines);
  const totalVat = Math.round(breakdown.reduce((s, r) => s + r.vat, 0) * 100) / 100;
  // Net = what was paid minus VAT. The gross total is shown in the Amount field above,
  // so here we decompose it: Net (excl. VAT) + VAT = that amount.
  const netTotal = Math.round((linesTotal - totalVat) * 100) / 100;

  return (
    <div className="vat-lines">
      <div className="vat-lines-head">
        <label style={{ margin: 0, display: "inline-flex", alignItems: "center", gap: 8 }}>
          VAT lines{validLines.length ? ` · ${validLines.length}` : ""}
          {hasSuggested ? (
            <span className="vat-suggested-tag" title={SUGGESTED_TIP}>
              <Icon.warn size={11} /> suggested
            </span>
          ) : null}
        </label>
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
                placeholder="€ total"
                value={l.amount}
                onChange={setLine(i, "amount")}
                inputMode="decimal"
                style={{ maxWidth: 84 }}
                title="Total paid for this line (incl. VAT)"
              />
              {(() => {
                const g = Number(l.amount) || 0;
                const rt = Number(l.vat_rate) || 0;
                const v = Math.round((g - g / (1 + rt / 100)) * 100) / 100;
                const n = Math.round((g - v) * 100) / 100;
                return (
                  <span
                    className="vat-line-split num"
                    title="Net and VAT for this line, from the total and rate"
                  >
                    {g > 0 ? <>net {money(n)} · VAT {money(v)}</> : null}
                  </span>
                );
              })()}
              <select
                className={`select${l.suggested ? " select-suggested" : ""}`}
                value={l.vat_rate ?? ""}
                onChange={setLine(i, "vat_rate")}
                style={{ maxWidth: 92 }}
                title={l.suggested ? SUGGESTED_TIP : undefined}
              >
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
                Net {money(netTotal)} · VAT {money(totalVat)} · Total {money(linesTotal)}
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
export function seedLines(expense, items, estimated = false) {
  if (items && items.length) {
    return items.map((li) => ({
      description: li.description || "",
      amount: li.amount ?? "",
      vat_rate: li.vat_rate == null ? "" : String(li.vat_rate),
      suggested: !!estimated,
    }));
  }
  if (expense.amount != null) {
    return [
      {
        description: "",
        amount: expense.amount,
        vat_rate: expense.vat_rate == null ? "" : String(expense.vat_rate),
        suggested: !!estimated,
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
    amount: expense.amount ?? "",
    expense_date: (expense.expense_date || "").slice(0, 10),
    category: expense.category || "",
  });
  const estimated = !!expense.raw_extraction?.vat_estimated;
  const [lines, setLines] = useState(() => seedLines(expense, null, estimated));
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  // Replace the seed with the extractor's stored line items once they load.
  useEffect(() => {
    let active = true;
    api
      .expenseLineItems(expense.id)
      .then((res) => {
        if (active && res.line_items?.length) setLines(seedLines(expense, res.line_items, estimated));
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [expense.id]);

  const validLines = lines.filter((l) => Number(l.amount) > 0);
  const linesTotal = Math.round(validLines.reduce((s, l) => s + Number(l.amount || 0), 0) * 100) / 100;
  const amountNum = Math.round((Number(form.amount) || 0) * 100) / 100;
  const vatMismatch = validLines.length > 0 && Math.abs(linesTotal - amountNum) > 0.01;

  const save = () => {
    const patch = { expense_date: form.expense_date, amount: amountNum };
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
            value={form.amount}
            onChange={set("amount")}
            inputMode="decimal"
            title="The full amount paid (incl. VAT) — the receipt's total"
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
      {vatMismatch ? (
        <p className="vat-lines-hint" style={{ color: "var(--amber, #b26b00)" }}>
          The VAT lines add up to {money(linesTotal)} but the amount paid is {money(amountNum)} —
          adjust the lines (and drop any discount line) so they match the receipt.
        </p>
      ) : null}

      <div className="litem-actions">
        <Button size="sm" variant="ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button size="sm" variant="primary" onClick={save} disabled={busy || amountNum <= 0}>
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

// The expense behind an exception (if any) — single source of truth for opening
// the detail view, sorting by recency, and unread tracking. Bank-only rows return null.
export function exceptionExpense(type, data) {
  if (type === "amount_mismatch") return data.expense || null;
  if (type === "duplicates") return Array.isArray(data) ? data[0] : null;
  if (type === "unmatched_bank") return null;
  return data; // missing_vat, unmatched_expenses
}

export function ExceptionItem({ type, data, onOpenExpense, isNew, onDelete }) {
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

  // The expense behind this exception (if any) — so the row can open the full
  // detail view (net/VAT/total, date, receipt). Bank-only rows have no expense.
  const expense = exceptionExpense(type, data);
  const canOpen = expense && typeof onOpenExpense === "function";

  return (
    <div className={`exc${isNew ? " exc-new" : ""}`}>
      <span className={`exc-ico ${meta.tone}`}>
        <Icon.warn size={16} />
      </span>
      <div
        className={`exc-body${canOpen ? " exc-body-click" : ""}`}
        {...(canOpen
          ? {
              role: "button",
              tabIndex: 0,
              title: "See net / VAT / total, date and receipt",
              onClick: () => onOpenExpense(expense),
              onKeyDown: (ev) => {
                if (ev.key === "Enter" || ev.key === " ") {
                  ev.preventDefault();
                  onOpenExpense(expense);
                }
              },
            }
          : {})}
      >
        <div className={`exc-kind ${meta.tone}`}>
          {meta.kind}
          {isNew ? <span className="exc-new-tag">New</span> : null}
        </div>
        <div className="exc-vendor">{vendor}</div>
        <div className="exc-detail">{detail}</div>
      </div>
      <div className="exc-actions">
        {expense && typeof onDelete === "function" ? (
          <button
            type="button"
            className="x-btn"
            title="Delete this expense"
            aria-label="Delete this expense"
            onClick={() => onDelete(expense)}
          >
            <Icon.x size={14} />
          </button>
        ) : null}
        <Link to={type === "duplicates" ? "/ledger?view=duplicates" : "/ledger"} className="btn btn-sm">
          Resolve
        </Link>
      </div>
    </div>
  );
}

// Flatten the exceptions payload into a single ordered list of {type, data}.
// NOTE: `unmatched_bank` is deliberately NOT flattened here — unmatched bank
// payments are collapsed into a single per-statement row (see BankStatementAlert
// and the Bank statements page), so they don't flood this list one-by-one.
export function flattenExceptions(exc) {
  if (!exc) return [];
  const out = [];
  const e = exc.exceptions || {};
  (e.duplicates || []).forEach((d) => out.push({ type: "duplicates", data: d }));
  (e.amount_mismatch || []).forEach((d) => out.push({ type: "amount_mismatch", data: d }));
  (e.missing_vat || []).forEach((d) => out.push({ type: "missing_vat", data: d }));
  (e.unmatched_expenses || []).forEach((d) => out.push({ type: "unmatched_expenses", data: d }));
  return out;
}

// Compact one-row summary of an imported statement that still has unmatched
// purchases — shown in the Reconciliation exceptions area in place of the many
// individual bank rows. Clicking it opens the statement in the Bank statements page.
export function BankStatementAlert({ statement: s, isNew, onOpen, onView }) {
  const period = s.period_start ? `${shortDate(s.period_start)} – ${shortDate(s.period_end)}` : "";
  const n = s.needs_receipt_count || 0;
  // The body opens the transactions popup in place; "View" navigates to the section.
  const open = () => onOpen?.(s);
  const view = () => (onView || onOpen)?.(s);
  return (
    <div className={`exc${isNew ? " exc-new" : ""}`}>
      <span className="exc-ico amber">
        <Icon.bank size={16} />
      </span>
      <div
        className="exc-body exc-body-click"
        role="button"
        tabIndex={0}
        title="See this statement's transactions"
        onClick={open}
        onKeyDown={(ev) => {
          if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            open();
          }
        }}
      >
        <div className="exc-kind amber">
          Bank statement imported
          {isNew ? <span className="exc-new-tag">New</span> : null}
        </div>
        <div className="exc-vendor">{s.filename || "Bank statement"}</div>
        <div className="exc-detail">
          {n} payment{n === 1 ? "" : "s"} still need{n === 1 ? "s" : ""} a receipt
          {period ? ` · ${period}` : ""} · {s.txn_count} transactions
        </div>
      </div>
      <div className="exc-actions">
        <button type="button" className="btn btn-sm" title="Open the Bank statements section" onClick={view}>
          View →
        </button>
      </div>
    </div>
  );
}

/* ---------- Ledger table ---------- */
const STATUS_CHOICES = [
  { value: "posted", label: "Posted" },
  { value: "pending_review", label: "Needs review" },
  { value: "confirmed", label: "Confirmed" },
];

export function LedgerTable({ expenses, onDelete, busyId, duplicateIds, onRowClick, onStatusChange, onCategoryChange, categories }) {
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
            <th className="right">Net</th>
            <th className="right">VAT</th>
            <th className="right">Total</th>
            <th>Status</th>
            <th>Receipt</th>
            {onDelete ? <th></th> : null}
          </tr>
        </thead>
        <tbody>
          {expenses.map((e) => {
            const isDup = duplicateIds?.has(e.id);
            const net = e.vat_amount != null ? Math.round((e.amount - e.vat_amount) * 100) / 100 : e.amount;
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
              <td className="cell-muted">
                {onCategoryChange ? (
                  <select
                    className="status-select"
                    value={e.category || "Uncategorized"}
                    title="Change category"
                    onClick={(ev) => ev.stopPropagation()}
                    onChange={(ev) => {
                      ev.stopPropagation();
                      onCategoryChange(e, ev.target.value);
                    }}
                    disabled={busyId === e.id}
                  >
                    {(categories || []).some((c) => c.name === (e.category || "Uncategorized")) ? null : (
                      <option value={e.category || "Uncategorized"}>{e.category || "Uncategorized"}</option>
                    )}
                    {(categories || []).map((c) => (
                      <option key={c.id} value={c.name}>{c.name}</option>
                    ))}
                  </select>
                ) : (
                  e.category || "Uncategorized"
                )}
              </td>
              <td className="cell-muted">
                {e.source === "card" ? "Card ending 4821" : sourceLabel(e.source)}
              </td>
              <td className="right num cell-muted">{money(net)}</td>
              <td className="right num cell-muted">{e.vat_amount != null ? money(e.vat_amount) : "—"}</td>
              <td className="right num">{money(e.amount)}</td>
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
