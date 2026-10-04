import { useState, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Modal, Button } from "./ui.jsx";
import { Icon } from "./icons.jsx";
import { api } from "../lib/api.js";
import { useToast } from "./toast.jsx";

export default function ImportBankModal({ onClose }) {
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [drag, setDrag] = useState(false);
  const inputRef = useRef();
  const qc = useQueryClient();
  const toast = useToast();

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await api.importBank(file);
      ["exceptions", "close", "expenses"].forEach((k) =>
        qc.invalidateQueries({ queryKey: [k] })
      );
      toast(`Imported ${res.imported} bank transactions`);
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
          aria-label="Upload a bank statement CSV"
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
              <>Drop your bank CSV or <b>browse</b></>
            )}
          </div>
        </div>
        <input ref={inputRef} type="file" accept=".csv,text/csv" hidden onChange={(e) => setFile(e.target.files[0])} />

        <p style={{ fontSize: 12, color: "var(--text-dim)", margin: 0, lineHeight: 1.5 }}>
          We expect columns for date, amount and description (standard bank export).
          Negative amounts are money out. Card expenses are then matched automatically on
          the Reconciliation page.
        </p>

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
