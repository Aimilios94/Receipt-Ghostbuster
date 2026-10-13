// Click a ledger row -> see the full breakdown behind that one expense: its
// line items, VAT categorized per rate (computed in code by the backend), and
// the receipt image. "Every number traces back to the ledger", one row deep.
import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Modal, Badge, StatusBadge, Loading } from "./ui.jsx";
import { Icon } from "./icons.jsx";
import { api } from "../lib/api.js";
import { money, shortDate, sourceLabel } from "../lib/format.js";

function paidWith(e) {
  return e.source === "card" ? "Card ending 4821" : sourceLabel(e.source);
}

export default function ExpenseDetailModal({ expense, onClose }) {
  const [showReceipt, setShowReceipt] = useState(false);
  const { data, isLoading } = useQuery({
    queryKey: ["line-items", expense.id],
    queryFn: () => api.expenseLineItems(expense.id),
  });

  const lines = data?.line_items || [];
  const breakdown = data?.vat_breakdown;
  const rates = breakdown?.rates || [];
  const linesAmount = lines.reduce((s, li) => s + Number(li.amount || 0), 0);
  const linesVat = lines.reduce((s, li) => s + Number(li.vat_amount || 0), 0);

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

        {/* Line items with amount + per-line rate */}
        <div className="detail-section-label">Line items</div>
        {isLoading ? (
          <Loading />
        ) : lines.length ? (
          <div className="table-wrap">
            <table className="ledger">
              <thead>
                <tr>
                  <th>Item</th>
                  <th className="right">Qty</th>
                  <th className="right">Amount</th>
                  <th className="right">VAT rate</th>
                  <th className="right">VAT</th>
                </tr>
              </thead>
              <tbody>
                {lines.map((li) => (
                  <tr key={li.id}>
                    <td className="cell-vendor">{li.description || "—"}</td>
                    <td className="right cell-muted">{li.quantity ?? "—"}</td>
                    <td className="right num">{money(li.amount)}</td>
                    <td className="right cell-muted">{li.vat_rate != null ? `${li.vat_rate}%` : "—"}</td>
                    <td className="right num cell-muted">{li.vat_amount != null ? money(li.vat_amount) : "—"}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="detail-total-row">
                  <td>Total</td>
                  <td></td>
                  <td className="right num">{money(linesAmount)}</td>
                  <td></td>
                  <td className="right num">{money(linesVat)}</td>
                </tr>
              </tfoot>
            </table>
          </div>
        ) : (
          <p className="vat-lines-hint" style={{ margin: 0 }}>
            No itemized lines stored for this expense (manual entry or an older receipt).
          </p>
        )}

        {/* Grand total */}
        <div className="detail-total">
          <span>Total</span>
          <span className="num">
            {money(expense.amount)}
            {expense.vat_amount ? (
              <span className="cell-muted" style={{ fontWeight: 400 }}>
                {" "}· incl. {money(expense.vat_amount)} VAT
                {breakdown?.net != null ? ` · net ${money(breakdown.net)}` : ""}
              </span>
            ) : null}
          </span>
        </div>

        {/* Receipt image */}
        {expense.receipt_image_url ? (
          <div style={{ marginTop: 4 }}>
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => setShowReceipt(true)}>
              <Icon.receipt size={13} /> View receipt
            </button>
          </div>
        ) : null}
      </div>

      {showReceipt ? (
        <div className="overlay receipt-lightbox" onMouseDown={() => setShowReceipt(false)}>
          <img src={expense.receipt_image_url} alt="Receipt" onMouseDown={(ev) => ev.stopPropagation()} />
        </div>
      ) : null}
    </Modal>
  );
}
