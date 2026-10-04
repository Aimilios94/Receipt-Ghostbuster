import { useState, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Modal, Button } from "./ui.jsx";
import { Icon } from "./icons.jsx";
import { api } from "../lib/api.js";
import { useToast } from "./toast.jsx";
import { currentMonth } from "../lib/format.js";

// Invalidate everything the new expense could touch.
function refreshAll(qc) {
  ["expenses", "review-queue", "exceptions", "close"].forEach((k) =>
    qc.invalidateQueries({ queryKey: [k] })
  );
}

export default function AddExpenseModal({ onClose, defaultTab = "snap", defaultSource = "card" }) {
  const [tab, setTab] = useState(defaultTab);
  const qc = useQueryClient();
  const toast = useToast();
  const { data: categories } = useQuery({ queryKey: ["categories"], queryFn: api.categories });

  return (
    <Modal title="Add expense" onClose={onClose}>
      <div className="modal-body">
        <div className="tabs">
          <button className={`tab ${tab === "snap" ? "active" : ""}`} onClick={() => setTab("snap")}>
            Snap a receipt
          </button>
          <button
            className={`tab ${tab === "manual" ? "active" : ""}`}
            onClick={() => setTab("manual")}
          >
            Manual / cash
          </button>
        </div>

        {tab === "snap" ? (
          <SnapForm
            defaultSource={defaultSource}
            onDone={(res) => {
              refreshAll(qc);
              const gate = res.gated_to === "pending_review";
              toast(
                gate
                  ? `${res.extraction?.vendor || "Receipt"} needs review (low confidence)`
                  : `Posted ${res.expense?.vendor || "receipt"}`,
                gate ? "err" : "ok"
              );
              onClose();
            }}
          />
        ) : (
          <ManualForm
            categories={categories}
            onDone={(exp) => {
              refreshAll(qc);
              toast(`Added ${exp.vendor || exp.category || "expense"}`);
              onClose();
            }}
          />
        )}
      </div>
    </Modal>
  );
}

function SnapForm({ onDone, defaultSource }) {
  const [file, setFile] = useState(null);
  const [source, setSource] = useState(defaultSource);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [drag, setDrag] = useState(false);
  const inputRef = useRef();

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await api.extract(file, source);
      onDone(res);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div
        className={`dropzone ${drag ? "drag" : ""}`}
        role="button"
        tabIndex={0}
        aria-label="Upload a receipt photo"
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
        }}
      >
        <Icon.camera size={26} />
        <div style={{ marginTop: 10 }}>
          {file ? (
            <>
              <b>{file.name}</b>
            </>
          ) : (
            <>
              Drop a receipt photo or <b>browse</b>
            </>
          )}
        </div>
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          hidden
          onChange={(e) => setFile(e.target.files[0])}
        />
      </div>

      <div className="field">
        <label>Paid with</label>
        <select className="select" value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="card">Card</option>
          <option value="cash">Cash</option>
        </select>
      </div>

      <p style={{ fontSize: 12, color: "var(--text-dim)", margin: 0, lineHeight: 1.5 }}>
        We read the receipt with a vision model. Low-confidence reads go to the review queue —
        nothing posts until you confirm it.
      </p>

      {err ? <div className="error-banner" style={{ margin: 0 }}>{err}</div> : null}

      <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 4 }}>
        <Button variant="primary" onClick={submit} disabled={!file || busy}>
          {busy ? "Reading…" : "Extract receipt"}
        </Button>
      </div>
    </>
  );
}

function ManualForm({ categories, onDone }) {
  const [form, setForm] = useState({
    vendor: "",
    amount: "",
    category: "",
    source: "cash",
    expense_date: new Date().toISOString().slice(0, 10),
    vat_rate: "",
    note: "",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const payload = {
        amount: Number(form.amount),
        source: form.source,
        expense_date: form.expense_date,
      };
      if (form.vendor) payload.vendor = form.vendor;
      if (form.category) payload.category = form.category;
      if (form.note) payload.note = form.note;
      if (form.vat_rate) payload.vat_rate = Number(form.vat_rate);
      const exp = await api.createExpense(payload);
      onDone(exp);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 15 }}>
      <div className="field-row">
        <div className="field">
          <label>Vendor</label>
          <input className="input" value={form.vendor} onChange={set("vendor")} placeholder="Corner Bakery" />
        </div>
        <div className="field" style={{ maxWidth: 130 }}>
          <label>Amount (€)</label>
          <input
            className="input num"
            value={form.amount}
            onChange={set("amount")}
            inputMode="decimal"
            placeholder="0.00"
            required
          />
        </div>
      </div>

      <div className="field-row">
        <div className="field">
          <label>Category</label>
          <select className="select" value={form.category} onChange={set("category")}>
            <option value="">Auto-categorize</option>
            {(categories || []).map((c) => (
              <option key={c.id} value={c.name}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field" style={{ maxWidth: 130 }}>
          <label>Paid with</label>
          <select className="select" value={form.source} onChange={set("source")}>
            <option value="cash">Cash</option>
            <option value="card">Card</option>
          </select>
        </div>
      </div>

      <div className="field-row">
        <div className="field">
          <label>Date</label>
          <input className="input" type="date" value={form.expense_date} onChange={set("expense_date")} />
        </div>
        <div className="field" style={{ maxWidth: 130 }}>
          <label>VAT rate (%)</label>
          <input className="input num" value={form.vat_rate} onChange={set("vat_rate")} placeholder="24" inputMode="decimal" />
        </div>
      </div>

      <div className="field">
        <label>Note</label>
        <input className="input" value={form.note} onChange={set("note")} placeholder="Optional" />
      </div>

      {err ? <div className="error-banner" style={{ margin: 0 }}>{err}</div> : null}

      <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
        <Button type="submit" variant="primary" disabled={busy || !form.amount}>
          {busy ? "Saving…" : "Add expense"}
        </Button>
      </div>
    </form>
  );
}
