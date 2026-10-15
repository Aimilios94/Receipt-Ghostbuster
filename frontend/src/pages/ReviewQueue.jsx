import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api.js";
import { money } from "../lib/format.js";
import { Card, Loading, ErrorBanner, Empty, Button } from "../components/ui.jsx";
import { Icon } from "../components/icons.jsx";
import { ReviewItem } from "../components/sections.jsx";
import AddExpenseModal from "../components/AddExpenseModal.jsx";
import { useToast } from "../components/toast.jsx";

// Confirmation message after posting — states what landed on the ledger, so the
// user doesn't have to open the Ledger to confirm the amount + VAT went through.
export function postedMessage(posted, exp, patch) {
  const who = posted?.vendor || patch?.vendor || exp.vendor || "Expense";
  const amount = posted?.amount ?? patch?.amount ?? exp.amount;
  const vat = posted?.vat_amount;
  const vatPart = vat ? ` incl. ${money(vat)} VAT` : "";
  return `Posted ${who} — ${money(amount)}${vatPart} added to your ledger`;
}

export default function ReviewQueue() {
  const qc = useQueryClient();
  const toast = useToast();
  const [busyId, setBusyId] = useState(null);
  const [showAdd, setShowAdd] = useState(false);
  const { data, isLoading, error } = useQuery({
    queryKey: ["review-queue"],
    queryFn: api.reviewQueue,
  });

  const items = data || [];

  const post = async (exp, patch) => {
    setBusyId(exp.id);
    try {
      const posted = await api.confirmExpense(exp.id, patch);
      ["review-queue", "expenses", "exceptions", "close", "line-items"].forEach((k) =>
        qc.invalidateQueries({ queryKey: [k] })
      );
      toast(postedMessage(posted, exp, patch));
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusyId(null);
    }
  };

  // Re-read this receipt from a clearer photo: extract the new image, then (only if it
  // read) remove the old low-quality row. The fresh read lands in review or auto-posts.
  const retake = async (exp, file) => {
    setBusyId(exp.id);
    try {
      const res = await api.extract(file, exp.source || "card");
      if (res.readable === false) {
        toast("Couldn't read that photo — keeping the original. Try a flatter, well-lit shot.", "err");
        return;
      }
      await api.deleteExpense(exp.id);
      ["review-queue", "expenses", "exceptions", "close", "line-items"].forEach((k) =>
        qc.invalidateQueries({ queryKey: [k] })
      );
      toast(
        res.gated_to === "posted"
          ? `Re-read ${res.expense?.vendor || "receipt"} — posted to your ledger`
          : "Re-read — updated in the review queue"
      );
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusyId(null);
    }
  };

  const discard = async (exp) => {
    setBusyId(exp.id);
    try {
      await api.deleteExpense(exp.id);
      ["review-queue", "expenses", "exceptions", "close", "line-items"].forEach((k) =>
        qc.invalidateQueries({ queryKey: [k] })
      );
      toast("Discarded");
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="rise">
      <div className="page-head">
        <div>
          <h1 className="page-title">Review queue</h1>
          <div className="page-sub">
            Receipts we couldn't read with confidence. Nothing posts to your ledger until you confirm it.
          </div>
        </div>
        <div className="head-actions">
          <Button variant="primary" icon={<Icon.plus size={15} />} onClick={() => setShowAdd(true)}>
            Add expense
          </Button>
        </div>
      </div>

      <ErrorBanner error={error} />

      <Card className="card-pad" style={{ maxWidth: 640 }}>
        {isLoading ? (
          <Loading />
        ) : items.length ? (
          items.map((e) => (
            <ReviewItem
              key={e.id}
              expense={e}
              busy={busyId === e.id}
              onPost={post}
              onDiscard={discard}
              onRetake={retake}
            />
          ))
        ) : (
          <Empty icon={<Icon.check size={30} />}>
            All caught up. Every receipt has been reviewed and posted.
          </Empty>
        )}
      </Card>

      {showAdd && <AddExpenseModal onClose={() => setShowAdd(false)} />}
    </div>
  );
}
