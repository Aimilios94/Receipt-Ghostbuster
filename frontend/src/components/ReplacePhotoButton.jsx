import { useRef, useState } from "react";
import { Icon } from "./icons.jsx";
import { api } from "../lib/api.js";
import { useToast } from "./toast.jsx";
import { useExpenseToast } from "../lib/month.jsx";

// Opens the photo picker, uploads a new photo of this receipt, replaces the stored
// image and re-reads it (amount / VAT / vendor / date refreshed when it reads
// cleanly). To change values by hand, use ExpenseEditModal instead.
export default function ReplacePhotoButton({ expenseId, onDone, hasPhoto = true }) {
  const inputRef = useRef();
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const expenseToast = useExpenseToast();

  const onFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-picking the same file
    if (!file || !expenseId) return;
    setBusy(true);
    try {
      const res = await api.rescanReceipt(expenseId, file);
      if (res.readable === false) {
        toast(res.message || "New photo saved — couldn't read it, kept the amounts.", "err");
      } else {
        expenseToast(res.expense, `Receipt updated${res.expense?.vendor ? ` — ${res.expense.vendor}` : ""}`, "Saved");
      }
      onDone?.(res.expense);
    } catch (err) {
      toast(err.message, "err");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button
        type="button"
        className="btn btn-sm btn-ghost"
        onClick={() => inputRef.current?.click()}
        disabled={busy || !expenseId}
        title="Upload a new photo of this receipt and read it again. This can change the amounts."
      >
        <Icon.camera size={13} /> {busy ? "Reading…" : hasPhoto ? "Replace photo" : "Add photo"}
      </button>
      <input ref={inputRef} type="file" accept="image/*" hidden onChange={onFile} />
    </>
  );
}
