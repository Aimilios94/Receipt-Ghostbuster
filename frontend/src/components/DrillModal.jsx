// Drill-down modal: click any dashboard number → see the exact expenses behind
// it, with a way to open each receipt. Lists are scoped by the caller so the
// total here always reconciles to the card you clicked ("one ledger, every
// number traces back to it").
import { useState, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Modal, Badge } from "./ui.jsx";
import { Icon } from "./icons.jsx";
import { api } from "../lib/api.js";
import { useToast } from "./toast.jsx";
import { money, shortDate, sourceLabel } from "../lib/format.js";

function paidWith(e) {
  return e.source === "card" ? "Card ending 4821" : sourceLabel(e.source);
}

function ReceiptCell({ expense, onView }) {
  if (!expense.receipt_image_url) return <span className="cell-muted">No receipt</span>;
  return (
    <button
      type="button"
      className="btn btn-sm btn-ghost"
      onClick={() => onView(expense.receipt_image_url)}
    >
      <Icon.receipt size={13} /> View
    </button>
  );
}

// mode: "amount" (default) | "vat" | "reconciled"
export default function DrillModal({ title, subtitle, expenses, mode = "amount", onClose }) {
  const [receipt, setReceipt] = useState(null);
  const [rows, setRows] = useState(expenses || []);
  const [busyId, setBusyId] = useState(null);
  const qc = useQueryClient();
  const toast = useToast();

  // Keep in sync if the caller passes a new list.
  useEffect(() => setRows(expenses || []), [expenses]);

  const remove = async (e) => {
    if (!window.confirm(`Delete ${e.vendor || "this expense"} (${money(e.amount)})? This can't be undone.`))
      return;
    setBusyId(e.id);
    try {
      await api.deleteExpense(e.id);
      ["expenses", "close", "exceptions", "review-queue", "subscriptions"].forEach((k) =>
        qc.invalidateQueries({ queryKey: [k] })
      );
      setRows((rs) => rs.filter((r) => r.id !== e.id));
      toast(`Deleted ${e.vendor || "expense"}`);
    } catch (err) {
      toast(err.message, "err");
    } finally {
      setBusyId(null);
    }
  };

  const sumAmount = rows.reduce((s, e) => s + Number(e.amount || 0), 0);
  const sumVat = rows.reduce((s, e) => s + Number(e.vat_amount || 0), 0);
  const matched = rows.filter((e) => e.reconciled || e.matched_transaction_id).length;

  // VAT grouped by rate (each expense carries one rate; mixed-rate receipts store
  // their dominant rate — a known simplification).
  const vatByRate =
    mode === "vat"
      ? Object.entries(
          rows.reduce((acc, e) => {
            const key = e.vat_rate != null ? `${e.vat_rate}%` : "Unknown rate";
            acc[key] = (acc[key] || 0) + Number(e.vat_amount || 0);
            return acc;
          }, {})
        ).sort((a, b) => b[1] - a[1])
      : [];

  let summary;
  if (mode === "vat") summary = `VAT paid: ${money(sumVat)} · across ${money(sumAmount)} of spend`;
  else if (mode === "reconciled")
    summary = `${matched} reconciled · ${rows.length - matched} left to reconcile`;
  else summary = `${rows.length} ${rows.length === 1 ? "expense" : "expenses"} · ${money(sumAmount)}`;

  return (
    <Modal title={title} onClose={onClose} width={760}>
      <div className="modal-body">
        <div className="drill-sum">
          {subtitle ? <span className="drill-sum-sub">{subtitle}</span> : null}
          <span className="drill-sum-total num">{summary}</span>
        </div>

        {mode === "vat" && vatByRate.length ? (
          <div className="vat-rates">
            {vatByRate.map(([rate, amt]) => (
              <span className="vat-rate-chip" key={rate}>
                <span className="vat-rate-pct">{rate}</span>
                <span className="num">{money(amt)}</span>
              </span>
            ))}
          </div>
        ) : null}

        {rows.length ? (
          <div className="table-wrap">
            <table className="ledger">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Where</th>
                  <th>Category</th>
                  <th>Paid with</th>
                  <th className="right">Amount</th>
                  {mode === "vat" ? <th className="right">VAT</th> : null}
                  {mode === "reconciled" ? <th>Bank match</th> : null}
                  <th className="right">Receipt</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((e) => (
                  <tr key={e.id}>
                    <td className="cell-date">{shortDate(e.expense_date)}</td>
                    <td className="cell-vendor">{e.vendor || "—"}</td>
                    <td className="cell-muted">{e.category || "Uncategorized"}</td>
                    <td className="cell-muted">{paidWith(e)}</td>
                    <td className="right num">{money(e.amount)}</td>
                    {mode === "vat" ? (
                      <td className="right num">
                        {e.vat_amount != null ? money(e.vat_amount) : "—"}
                        {e.vat_rate ? <span className="cell-muted"> @{e.vat_rate}%</span> : null}
                      </td>
                    ) : null}
                    {mode === "reconciled" ? (
                      <td>
                        {e.reconciled || e.matched_transaction_id ? (
                          <Badge tone="green" icon={<Icon.check size={12} />}>Matched</Badge>
                        ) : (
                          <Badge tone="amber" icon={<Icon.warn size={12} />}>Not yet</Badge>
                        )}
                      </td>
                    ) : null}
                    <td className="right">
                      <ReceiptCell expense={e} onView={setReceipt} />
                    </td>
                    <td className="right">
                      <button
                        type="button"
                        className="x-btn"
                        title={`Delete ${e.vendor || "expense"}`}
                        aria-label={`Delete ${e.vendor || "expense"}`}
                        onClick={() => remove(e)}
                        disabled={busyId === e.id}
                      >
                        <Icon.x size={15} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty">Nothing here for this month.</div>
        )}
      </div>

      {receipt ? (
        <div className="overlay receipt-lightbox" onMouseDown={() => setReceipt(null)}>
          <img src={receipt} alt="Receipt" onMouseDown={(e) => e.stopPropagation()} />
        </div>
      ) : null}
    </Modal>
  );
}
