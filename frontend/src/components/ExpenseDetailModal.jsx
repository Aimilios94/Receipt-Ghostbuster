// Click a ledger row -> see the full breakdown behind that one expense: its
// line items, VAT categorized per rate (computed in code by the backend), and
// the receipt image. "Every number traces back to the ledger", one row deep.
import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Modal, Badge, StatusBadge, Loading } from "./ui.jsx";
import { Icon } from "./icons.jsx";
import { api } from "../lib/api.js";
import { money, shortDate, sourceLabel } from "../lib/format.js";
import EditReceiptButton from "./EditReceiptButton.jsx";
import { ReceiptLightbox } from "./ReceiptLightbox.jsx";

function paidWith(e) {
  return e.source === "card" ? "Card ending 4821" : sourceLabel(e.source);
}

export default function ExpenseDetailModal({ expense: expenseProp, onClose }) {
  const [showReceipt, setShowReceipt] = useState(false);
  // Local copy so a receipt re-scan updates this view in place.
  const [expense, setExpense] = useState(expenseProp);
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["line-items", expense.id],
    queryFn: () => api.expenseLineItems(expense.id),
  });

  const onRescanned = (updated) => {
    if (updated) setExpense(updated);
    ["expenses", "line-items", "exceptions", "close", "statements"].forEach((k) =>
      qc.invalidateQueries({ queryKey: [k] })
    );
  };

  const lines = data?.line_items || [];
  const breakdown = data?.vat_breakdown;
  const rates = breakdown?.rates || [];
  const linesAmount = Math.round(lines.reduce((s, li) => s + Number(li.amount || 0), 0) * 100) / 100;
  const linesVat = Math.round(lines.reduce((s, li) => s + Number(li.vat_amount || 0), 0) * 100) / 100;
  const linesNet = Math.round((linesAmount - linesVat) * 100) / 100;
  // Prefer the itemized sums for the grand total — they reconcile net + VAT = paid even
  // when the stored expense.amount is off (e.g. the model read the net base as the total).
  const hasLines = lines.length > 0;
  const vatShown = hasLines ? linesVat : expense.vat_amount;
  const netShown = hasLines
    ? linesNet
    : expense.vat_amount != null
    ? Math.round((expense.amount - expense.vat_amount) * 100) / 100
    : expense.amount;
  const totalShown = hasLines ? linesAmount : expense.amount;

  return (
    <Modal title={expense.vendor || "Expense"} onClose={onClose} width={720}>
      <div className="modal-body">
        {/* Summary header */}
        <div className="detail-head">
          <div className="detail-head-meta">
            <span>{shortDate(expense.expense_date)}</span>
            <span>·</span>
            <span>{paidWith(expense)}</span>
            <span>·</span>
            <span>{expense.category || "Uncategorized"}</span>
            <StatusBadge expense={expense} />
          </div>
          <div className="detail-head-amt num">{money(expense.amount)}</div>
        </div>

        {/* VAT categorized per rate */}
        <div className="detail-section-label">
          VAT by rate
          {expense.vat_amount != null ? (
            <span className="cell-muted"> · total {money(expense.vat_amount)}</span>
          ) : null}
        </div>
        {rates.length ? (
          <div className="vat-rates">
            {rates.map((r) => (
              <span className="vat-rate-chip" key={r.rate}>
                <span className="vat-rate-pct">{r.rate}%</span>
                <span className="num">{money(r.vat_amount)}</span>
                <span className="cell-muted" style={{ fontSize: 11 }}>on {money(r.gross)}</span>
              </span>
            ))}
          </div>
        ) : expense.vat_amount ? (
          <div className="vat-rates">
            <span className="vat-rate-chip">
              <span className="vat-rate-pct">{expense.vat_rate != null ? `${expense.vat_rate}%` : "VAT"}</span>
              <span className="num">{money(expense.vat_amount)}</span>
            </span>
          </div>
        ) : (
          <p className="vat-lines-hint" style={{ margin: 0 }}>No VAT recorded for this expense.</p>
        )}

        {/* Named products the model actually read (from the raw extraction) — the
            stored "Line items" below are VAT-rate buckets, so this shows what was bought. */}
        {(() => {
          const products = (expense.raw_extraction?.line_items || []).filter(
            (p) => (p.description || "").trim()
          );
          if (!products.length) return null;
          return (
            <>
              <div className="detail-section-label">Products on this receipt · {products.length}</div>
              <div className="table-wrap">
                <table className="ledger">
                  <thead>
                    <tr>
                      <th>Product</th>
                      <th className="right">Amount</th>
                      <th className="right">VAT rate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {products.map((p, i) => (
                      <tr key={i}>
                        <td className="cell-vendor">{p.description}</td>
                        <td className="right num">{p.amount != null ? money(p.amount) : "—"}</td>
                        <td className="right cell-muted">{p.vat_rate != null ? `${p.vat_rate}%` : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          );
        })()}

        {/* Line items with amount + per-line rate (VAT-rate buckets) */}
        <div className="detail-section-label">VAT breakdown</div>
        {isLoading ? (
          <Loading />
        ) : lines.length ? (
          <div className="table-wrap">
            <table className="ledger">
              <thead>
                <tr>
                  <th>Item</th>
                  <th className="right">Qty</th>
                  <th className="right">Net</th>
                  <th className="right">VAT</th>
                  <th className="right">Total</th>
                  <th className="right">VAT rate</th>
                </tr>
              </thead>
              <tbody>
                {lines.map((li) => {
                  const vat = li.vat_amount;
                  const net = vat != null ? Math.round((li.amount - vat) * 100) / 100 : li.amount;
                  return (
                    <tr key={li.id}>
                      <td className="cell-vendor">{li.description || "—"}</td>
                      <td className="right cell-muted">{li.quantity ?? "—"}</td>
                      <td className="right num cell-muted">{money(net)}</td>
                      <td className="right num cell-muted">{vat != null ? money(vat) : "—"}</td>
                      <td className="right num">{money(li.amount)}</td>
                      <td className="right cell-muted">{li.vat_rate != null ? `${li.vat_rate}%` : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr className="detail-total-row">
                  <td>Total</td>
                  <td></td>
                  <td className="right num">{money(linesNet)}</td>
                  <td className="right num">{money(linesVat)}</td>
                  <td className="right num">{money(linesAmount)}</td>
                  <td></td>
                </tr>
              </tfoot>
            </table>
          </div>
        ) : (
          <p className="vat-lines-hint" style={{ margin: 0 }}>
            No itemized lines stored for this expense (manual entry or an older receipt).
          </p>
        )}

        {/* Grand total — Net (total) · VAT (total) · Paid (net + VAT = full amount paid) */}
        <div className="detail-total">
          <span>Totals</span>
          <span className="num">
            {vatShown ? (
              <span className="cell-muted" style={{ fontWeight: 400 }}>
                Net (total) {money(netShown)} · VAT (total) {money(vatShown)} ·{" "}
              </span>
            ) : null}
            Paid {money(totalShown)}
          </span>
        </div>

        {/* Receipt image + replace-photo */}
        <div style={{ marginTop: 4, display: "flex", gap: 8, flexWrap: "wrap" }}>
          {expense.receipt_image_url ? (
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => setShowReceipt(true)}>
              <Icon.receipt size={13} /> View receipt
            </button>
          ) : null}
          <EditReceiptButton
            expenseId={expense.id}
            onDone={onRescanned}
            label={expense.receipt_image_url ? "Edit" : "Add photo"}
          />
        </div>
      </div>

      {showReceipt ? (
        <ReceiptLightbox src={expense.receipt_image_url} onClose={() => setShowReceipt(false)} />
      ) : null}
    </Modal>
  );
}
