// Undo for deletes. The backend returns a snapshot of the deleted row and its VAT
// lines, and Undo puts it back with the same id, so links to it stay valid. The
// receipt photo is never removed from storage, so nothing is lost.
import { useQueryClient } from "@tanstack/react-query";
import { api } from "./api.js";
import { money } from "./format.js";
import { useToast } from "../components/toast.jsx";

export const UNDO_TOAST_MS = 8000;

const LEDGER_KEYS = [
  "expenses", "exceptions", "close", "review-queue", "line-items", "subscriptions", "statements", "photo-names",
];

export function useRefreshLedger() {
  const qc = useQueryClient();
  return () => LEDGER_KEYS.forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
}

// Returns remove(expense, { message, onRestored }). Throws if the delete fails, so
// callers keep their own error handling.
export function useDeleteWithUndo() {
  const toast = useToast();
  const refresh = useRefreshLedger();
  return async (exp, { message, onRestored } = {}) => {
    const res = await api.deleteExpense(exp.id);
    refresh();
    const label = `${exp.vendor || "expense"} ${money(exp.amount)}`;
    const snapshot = res?.snapshot;
    if (!snapshot?.expense) {
      toast(message || `Deleted ${label}`);
      return;
    }
    toast(message || `Deleted ${label}`, "ok", {
      duration: UNDO_TOAST_MS,
      action: {
        label: "Undo",
        onClick: async () => {
          try {
            const r = await api.restoreExpense(snapshot);
            refresh();
            onRestored?.(r.expense);
            toast(
              snapshot.expense.matched_transaction_id && !r.match_restored
                ? `Restored ${label}. Its bank line is matched to something else now, so it's unmatched.`
                : `Restored ${label}`
            );
          } catch (e) {
            toast(e.message, "err");
          }
        },
      },
    });
  };
}
