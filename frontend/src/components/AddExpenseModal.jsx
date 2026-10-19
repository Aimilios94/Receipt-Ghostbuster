import { useState, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Modal, Button } from "./ui.jsx";
import { Icon } from "./icons.jsx";
import { ReceiptLightbox } from "./ReceiptLightbox.jsx";
import { api } from "../lib/api.js";
import { useToast } from "./toast.jsx";
import { currentMonth, money, shortDate } from "../lib/format.js";

// Invalidate everything the new expense could touch.
function refreshAll(qc) {
  ["expenses", "review-queue", "exceptions", "close", "line-items"].forEach((k) =>
    qc.invalidateQueries({ queryKey: [k] })
  );
}

// One receipt's summary in the duplicate-comparison view: vendor, date, category,
// the Net / VAT / Total split, and a button to view the receipt image for comparison.
function DupCard({ title, exp, highlight, onView }) {
  const vat = exp.vat_amount;
  const net = vat != null ? Math.round((exp.amount - vat) * 100) / 100 : exp.amount;
  return (
    <div className={`dup-card${highlight ? " dup-card-new" : ""}`}>
      <div className="dup-card-title">{title}</div>
      <div className="dup-card-vendor">{exp.vendor || "—"}</div>
      <div className="dup-card-sub">
        {shortDate(exp.expense_date)}
        {exp.category ? ` · ${exp.category}` : ""}
      </div>
      <div className="dup-card-figs">
        <span>Net <b className="num">{money(net)}</b></span>
        <span>VAT <b className="num">{vat != null ? money(vat) : "—"}</b></span>
        <span>Total <b className="num">{money(exp.amount)}</b></span>
      </div>
      {exp.receipt_image_url ? (
        <button type="button" className="btn btn-sm btn-ghost" onClick={() => onView(exp.receipt_image_url)}>
          <Icon.receipt size={13} /> View receipt
        </button>
      ) : (
        <div className="dup-card-sub">No receipt image</div>
      )}
    </div>
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
            onRefresh={() => refreshAll(qc)}
            onClose={onClose}
            onDone={(res) => {
              refreshAll(qc);
              if (res.gated_to === "pending_review") {
                toast(
                  res.issues?.length
                    ? `Sent to review — ${res.issues[0]}`
                    : `${res.extraction?.vendor || "Receipt"} needs review`,
                  "err"
                );
              } else {
                toast(`Posted ${res.expense?.vendor || "receipt"}`);
              }
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

function SnapForm({ onDone, onRefresh, onClose, defaultSource }) {
  const toast = useToast();
  const [file, setFile] = useState(null);
  const [source, setSource] = useState(defaultSource);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [issues, setIssues] = useState([]);
  const [dup, setDup] = useState(null);
  const [lowQuality, setLowQuality] = useState(null);
  const [lightbox, setLightbox] = useState(null);
  const [discarding, setDiscarding] = useState(false);
  const [drag, setDrag] = useState(false);
  const inputRef = useRef();

  // User chose to retake: discard the low-quality read and return to the dropzone.
  const retake = async () => {
    try {
      if (lowQuality?.expense?.id) await api.deleteExpense(lowQuality.expense.id);
    } catch {
      /* best-effort cleanup */
    }
    onRefresh?.();
    setLowQuality(null);
    setFile(null);
  };

  // Discard the just-uploaded (review-queued) row when it's the duplicate.
  const discardUpload = async () => {
    setDiscarding(true);
    try {
      await api.deleteExpense(dup.created.id);
      onRefresh?.();
      toast("Duplicate upload discarded");
      onClose();
    } catch (e) {
      setErr(e.message);
      setDiscarding(false);
    }
  };

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    setErr(null);
    setIssues([]);
    try {
      const res = await api.extract(file, source, note);
      // Guardrail: unreadable receipt — keep the modal open, ask for a better photo.
      if (res.readable === false) {
        setErr("We couldn't read this receipt clearly. Try a flatter, well-lit photo with the total and date in frame.");
        setIssues(res.issues || []);
        return;
      }
      // Possible duplicate — open the comparison view so the user can check the new
      // upload against the matching ledger entries (nets, VAT, totals, receipts) and
      // reconcile it right here. The new row sits in review until they decide.
      if (res.duplicate_of?.length) {
        onRefresh?.();
        setDup({ matches: res.duplicate_of, created: res.expense });
        return;
      }
      // Hard-to-read (crumpled/low-light) -> offer a retake before it sits in review.
      if (res.retake_suggested) {
        onRefresh?.();
        setLowQuality(res);
        return;
      }
      onDone(res);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (lowQuality) {
    const issue = lowQuality.issues?.[0];
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div className="error-banner" style={{ margin: 0 }}>
          <b>This receipt was hard to read.</b> It looks crumpled, folded, or low-light, so some
          values may be wrong{issue ? ` — ${issue}` : "."} For an accurate read, retake a{" "}
          <b>flat, upright, well-lit</b> photo. Or continue and fix it yourself in the review queue.
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
          <Button variant="ghost" onClick={() => onDone(lowQuality)}>
            Continue to review
          </Button>
          <Button variant="primary" onClick={retake}>
            <Icon.camera size={14} /> Retake photo
          </Button>
        </div>
      </div>
    );
  }

  if (dup) {
    const matches = dup.matches || [];
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div className="error-banner" style={{ margin: 0 }}>
          <b>Possible duplicate.</b> This receipt matches {matches.length > 1 ? `${matches.length} entries` : "an entry"} already
          in your ledger. Compare them below — <b>discard this upload</b> if it's the same purchase,
          or <b>keep it</b> if it's genuinely separate. Nothing is posted until you decide.
        </div>
        <div className="dup-grid">
          <DupCard title="New upload" exp={dup.created} highlight onView={setLightbox} />
          {matches.map((m) => (
            <DupCard key={m.id} title="Already in ledger" exp={m} onView={setLightbox} />
          ))}
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
          <Button variant="ghost" onClick={discardUpload} disabled={discarding}>
            {discarding ? "Discarding…" : "Discard this upload"}
          </Button>
          <Button variant="primary" onClick={onClose} disabled={discarding}>
            Keep it (review later)
          </Button>
        </div>
        {err ? <div className="error-banner" style={{ margin: 0 }}>{err}</div> : null}
        {lightbox ? <ReceiptLightbox src={lightbox} onClose={() => setLightbox(null)} /> : null}
      </div>
    );
  }

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

      <div className="field">
        <label>Note for the extractor (optional)</label>
        <textarea
          className="input"
          rows={2}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="A hint if something's hard to read — e.g. 'the date is handwritten at the top', 'this is a fuel receipt', 'VAT is 0% (tobacco)'."
        />
      </div>

      <div className="hint">
        <Icon.camera size={14} />
        <span>
          <b>For the best read:</b> lay the receipt flat and upright, fill the frame, and use good
          light — avoid angles, folds and shadows. Dates and totals read far more reliably that way.
        </span>
      </div>

      <p style={{ fontSize: 12, color: "var(--text-dim)", margin: 0, lineHeight: 1.5 }}>
        We read the receipt with a vision model. Low-confidence or odd-looking reads go to the
        review queue — nothing posts until you confirm it. You can always edit it before posting.
      </p>

      {err ? (
        <div className="error-banner" style={{ margin: 0 }}>
          {err}
          {issues.length ? (
            <ul style={{ margin: "8px 0 0", paddingLeft: 18, lineHeight: 1.5 }}>
              {issues.map((it, i) => (
                <li key={i}>{it}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

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
