// Edit an already-posted expense (from a dashboard drill-down or the ledger):
// vendor, date, category, how it was paid (card or cash), and the per-rate VAT lines. Reuses the same VAT-lines
// editor as the review queue so a mixed-rate receipt is edited the same way.
import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Modal, Button } from "./ui.jsx";
import { VatLinesEditor, seedLines } from "./sections.jsx";
import { api } from "../lib/api.js";
import { useToast } from "./toast.jsx";
import { useExpenseToast } from "../lib/month.jsx";
import { money } from "../lib/format.js";
import { useRefreshLedger, UNDO_TOAST_MS } from "../lib/undo.jsx";

// Compare VAT lines by what would be saved, so loading them doesn't count as a change.
const linesKey = (lines) =>
  JSON.stringify(lines.map((l) => [l.description || "", Number(l.amount) || 0, String(l.vat_rate ?? "")]));

export default function ExpenseEditModal({ expense, onClose, onSaved }) {
  const qc = useQueryClient();
  const toast = useToast();
  const expenseToast = useExpenseToast();
  const { data: categories } = useQuery({ queryKey: ["categories"], queryFn: api.categories });
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    vendor: expense.vendor || "",
    amount: expense.amount ?? "",
    expense_date: (expense.expense_date || "").slice(0, 10),
    category: expense.category || "",
    source: expense.source || "card",
  });
  const refresh = useRefreshLedger();
  const estimated = !!expense.raw_extraction?.vat_estimated;
  const [lines, setLines] = useState(() => seedLines(expense, null, estimated));
  const [savedLinesKey, setSavedLinesKey] = useState(() => linesKey(seedLines(expense, null, estimated)));
  const [initialLines, setInitialLines] = useState(() => seedLines(expense, null, estimated));
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  useEffect(() => {
    let active = true;
    api
      .expenseLineItems(expense.id)
      .then((res) => {
        if (active && res.line_items?.length) {
          const seeded = seedLines(expense, res.line_items, estimated);
          setLines(seeded);
          setInitialLines(seeded);
          setSavedLinesKey(linesKey(seeded));
        }
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
  const sourceChanged = form.source !== (expense.source || "card");

  const toApiLines = (ls) =>
    ls
      .filter((l) => Number(l.amount) > 0)
      .map((l) => ({
        description: l.description || null,
        amount: Number(l.amount),
        vat_rate: l.vat_rate === "" || l.vat_rate == null ? null : Number(l.vat_rate),
      }));

  // Put the values back as they were before this save, including the bank match a
  // change to cash removed, when that bank line is still free.
  const undoEdit = async (linesChanged) => {
    const label = `${expense.vendor || "expense"} ${money(expense.amount)}`;
    try {
      const back = { expense_date: (expense.expense_date || "").slice(0, 10), amount: Number(expense.amount) };
      if (expense.vendor) back.vendor = expense.vendor;
      if (expense.category) back.category = expense.category;
      if (sourceChanged) back.source = expense.source || "card";
      if (linesChanged) back.line_items = toApiLines(initialLines);
      await api.updateExpense(expense.id, back);
      let relinked = true;
      const txnId = expense.matched_transaction_id;
      if (sourceChanged && txnId) {
        const state = await api.reconcileState();
        relinked = (state.unmatched_bank_list || []).some((t) => t.id === txnId);
        if (relinked) await api.matchExpense(expense.id, txnId);
      }
      refresh();
      onSaved?.();
      toast(
        relinked
          ? `Undid the edit to ${label}`
          : `Undid the edit to ${label}. Its bank line is matched to something else now, so it's unmatched.`
      );
    } catch (e) {
      toast(e.message, "err");
    }
  };

  const save = async () => {
    setBusy(true);
    try {
      const patch = { expense_date: form.expense_date, amount: amountNum };
      if (form.vendor) patch.vendor = form.vendor;
      if (form.category) patch.category = form.category;
      if (sourceChanged) patch.source = form.source;
      // Send the lines only if they changed: saving them recalculates the VAT, which
      // a vendor or date edit must not do.
      const linesChanged = linesKey(lines) !== savedLinesKey;
      if (linesChanged) patch.line_items = toApiLines(lines);
      const saved = await api.updateExpense(expense.id, patch);
      ["expenses", "close", "exceptions", "review-queue", "line-items", "subscriptions"].forEach((k) =>
        qc.invalidateQueries({ queryKey: [k] })
      );
      expenseToast(saved, `Saved ${saved?.vendor || "expense"} — ${money(saved?.amount)} updated`, "Saved", [
        { label: "Undo", onClick: () => undoEdit(linesChanged) },
      ]);
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
          <div className="field" style={{ maxWidth: 130 }}>
            <label>Paid with</label>
            <select className="select" value={form.source} onChange={set("source")}>
              <option value="card">Card</option>
              <option value="cash">Cash</option>
              {form.source !== "card" && form.source !== "cash" ? (
                <option value={form.source}>{form.source}</option>
              ) : null}
            </select>
          </div>
        </div>
        {sourceChanged ? (
          <p className="vat-lines-hint">
            {form.source === "cash"
              ? expense.matched_transaction_id
                ? "Cash isn't reconciled, so this expense's bank match will be removed. Undo puts it back."
                : "Cash isn't reconciled, so this expense leaves reconciliation."
              : "As a card payment it joins reconciliation, unmatched until you match it to a bank line."}
          </p>
        ) : null}

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
