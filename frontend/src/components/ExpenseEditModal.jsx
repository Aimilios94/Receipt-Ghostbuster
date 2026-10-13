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
    expense_date: (expense.expense_date || "").slice(0, 10),
    category: expense.category || "",
  });
  const [lines, setLines] = useState(() => seedLines(expense, null));
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

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

  const save = async () => {
    setBusy(true);
    try {
      const patch = { expense_date: form.expense_date, amount: linesTotal };
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
            <input className="input num" value={linesTotal} disabled title="Sum of the VAT lines below" />
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

        <div className="litem-actions" style={{ marginTop: 12 }}>
          <Button size="sm" variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button size="sm" variant="primary" onClick={save} disabled={busy || linesTotal <= 0}>
            Save changes
          </Button>
        </div>
      </div>
    </Modal>
  );
}
