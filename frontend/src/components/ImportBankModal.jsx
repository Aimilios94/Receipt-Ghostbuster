import { useState, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Modal, Button } from "./ui.jsx";
import { Icon } from "./icons.jsx";
import { api } from "../lib/api.js";
import { useToast } from "./toast.jsx";

export default function ImportBankModal({ onClose }) {
  const [file, setFile] = useState(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [drag, setDrag] = useState(false);
  const inputRef = useRef();
  const qc = useQueryClient();
  const toast = useToast();

  const isPdf = file && /\.pdf$/i.test(file.name);

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await api.importBank(file, undefined, note);
      ["exceptions", "close", "expenses", "statements"].forEach((k) =>
        qc.invalidateQueries({ queryKey: [k] })
      );
      const skipped = res.skipped ? ` · skipped ${res.skipped} already imported` : "";
      toast(
        res.imported === 0
          ? (res.message || "All transactions were already imported — nothing new.")
          : `Imported ${res.imported} bank transaction${res.imported === 1 ? "" : "s"}` +
              `${res.source === "pdf" ? " from PDF" : ""}${skipped}`
      );
      onClose();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="Import bank statement" onClose={onClose}>
      <div className="modal-body">
        <div
          className={`dropzone ${drag ? "drag" : ""}`}
          role="button"
          tabIndex={0}
          aria-label="Upload a bank statement CSV or PDF"
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
          <Icon.bank size={26} />
          <div style={{ marginTop: 10 }}>
            {file ? <b>{file.name}</b> : (
              <>Drop your bank CSV or PDF, or <b>browse</b></>
            )}
          </div>
        </div>
        <input ref={inputRef} type="file" accept=".csv,text/csv,.pdf,application/pdf" hidden onChange={(e) => setFile(e.target.files[0])} />

        <p style={{ fontSize: 12, color: "var(--text-dim)", margin: 0, lineHeight: 1.5 }}>
          Upload a <b>CSV</b> (columns for date, amount and description — the standard bank
          export) or, if you can't get a CSV, a <b>text-based PDF</b> statement. Negative
          amounts are money out. Card expenses are then matched automatically on the
          Reconciliation page.
        </p>

        <div className="field">
          <label>Note for the extractor (optional)</label>
          <textarea
            className="input"
            rows={2}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={
              isPdf
                ? "A hint for reading the PDF — e.g. 'debits are the left column', 'dates are DD-MM-YYYY', 'ignore the summary at the top'."
                : "Used when importing a PDF statement — e.g. an unusual date format or which column is the amount."
            }
          />
        </div>

        {err ? <div className="error-banner" style={{ margin: 0 }}>{err}</div> : null}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 4 }}>
          <Button variant="primary" icon={<Icon.upload size={15} />} onClick={submit} disabled={!file || busy}>
            {busy ? "Importing…" : "Import statement"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
