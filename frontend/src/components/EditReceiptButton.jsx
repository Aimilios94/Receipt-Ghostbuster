import { useRef, useState } from "react";
import { Icon } from "./icons.jsx";
import { api } from "../lib/api.js";
import { useToast } from "./toast.jsx";

// A small "Edit" action that sits next to a "View receipt" button. It opens the
// photo picker, uploads a new photo of that receipt, replaces the stored image and
// re-reads it (amount / VAT / vendor / date refreshed when it reads cleanly).
export default function EditReceiptButton({ expenseId, onDone, label = "Edit" }) {
  const inputRef = useRef();
  const [busy, setBusy] = useState(false);
  const toast = useToast();

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
        toast(`Receipt updated${res.expense?.vendor ? ` — ${res.expense.vendor}` : ""}`);
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
        title="Replace this receipt's photo with a new one and re-read it"
      >
        <Icon.edit size={13} /> {busy ? "Reading…" : label}
      </button>
      <input ref={inputRef} type="file" accept="image/*" hidden onChange={onFile} />
    </>
  );
}
