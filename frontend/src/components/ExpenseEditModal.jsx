// Edit an already-posted expense (from a dashboard drill-down or the ledger):
// vendor, date, category, and the per-rate VAT lines. Reuses the same VAT-lines
// editor as the review queue so a mixed-rate receipt is edited the same way.
import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Modal, Button } from "./ui.jsx";
import { VatLinesEditor, seedLines } from "./sections.jsx";
import { api } from "../lib/api.js";
import { useToast } from "./toast.jsx";
import { money } from "../lib/format.js";

export default function ExpenseEditModal({ expense, onClose, onSaved }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: categories } = useQuery({ queryKey: ["categories"], queryFn: api.categories });
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    vendor: expense.vendor || "",
    amount: expense.amount ?? "",
    expense_date: (expense.expense_date || "").slice(0, 10),
    category: expense.category || "",
  });
  const estimated = !!expense.raw_extraction?.vat_estimated;
  const [lines, setLines] = useState(() => seedLines(expense, null, estimated));
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

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

  const save = async () => {
    setBusy(true);
    try {
      const patch = { expense_date: form.expense_date, amount: amountNum };
      if (form.vendor) patch.vendor = form.vendor;
      if (form.category) patch.category = form.category;
      patch.line_items = validLines.map((l) => ({
        description: l.description || null,
        amount: Number(l.amount),
        vat_rate: l.vat_rate === "" || l.vat_rate == null ? null : Number(l.vat_rate),
      }));
      const saved = await api.confirmExpense(expense.id, patch);
      ["expenses", "close", "exceptions", "review-queue", "line-items", "subscriptions"].forEach((k) =>
        qc.invalidateQueries({ queryKey: [k] })
      );
      toast(`Saved ${saved?.vendor || "expense"} — ${money(saved?.amount)} updated`);
      onSaved?.(saved);
      onClose();
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={`Edit ${expense.vendor || "expense"}`} onClose={onClose} width={620}>
      <div className="modal-body">
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

        <div className="litem-actions" style={{ marginTop: 12 }}>
          <Button size="sm" variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button size="sm" variant="primary" onClick={save} disabled={busy || amountNum <= 0}>
            Save changes
          </Button>
        </div>
      </div>
    </Modal>
  );
}
