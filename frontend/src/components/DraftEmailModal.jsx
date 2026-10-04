import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Modal, Button } from "./ui.jsx";
import { Icon } from "./icons.jsx";
import { api } from "../lib/api.js";
import { money } from "../lib/format.js";
import { useToast } from "./toast.jsx";

// Draft a cancellation/refund email for a subscription. Draft-only: nothing is
// sent here. The user copies it, or (once n8n is wired) pushes it to Gmail drafts.
export default function DraftEmailModal({ sub, onClose }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [action, setAction] = useState("cancel");
  const [draft, setDraft] = useState(null); // { id, subject, email_draft, recipient }
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [delivering, setDelivering] = useState(false);
  const [err, setErr] = useState(null);

  const { data: health } = useQuery({ queryKey: ["health"], queryFn: api.health });
  const n8nReady = !!health?.config?.n8n_configured;

  const generate = async (act) => {
    setLoading(true);
    setErr(null);
    try {
      const ra = await api.draftRefundEmail(sub.id, act);
      setDraft(ra);
    } catch (e) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    generate(action);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [action]);

  const copy = async () => {
    await navigator.clipboard.writeText(`Subject: ${draft.subject}\n\n${draft.email_draft}`);
    toast("Draft copied to clipboard");
  };

  const approveAndCancel = async () => {
    setSaving(true);
    try {
      // Record the handled action + savings, and cancel the subscription.
      await api.updateRefundAction(draft.id, {
        subject: draft.subject,
        email_draft: draft.email_draft,
        recipient: draft.recipient || null,
        status: "done",
        saved_amount: sub.annual_cost,
      });
      await api.updateSubscription(sub.id, { status: "cancelled" });
      qc.invalidateQueries({ queryKey: ["subscriptions"] });
      qc.invalidateQueries({ queryKey: ["refund-actions"] });
      toast(`Cancelled ${sub.vendor} — ${money(sub.annual_cost)}/yr saved`);
      onClose();
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setSaving(false);
    }
  };

  const saveToGmail = async () => {
    setDelivering(true);
    try {
      // Persist any edits first, then have n8n create the Gmail draft.
      await api.updateRefundAction(draft.id, {
        subject: draft.subject,
        email_draft: draft.email_draft,
        recipient: draft.recipient || null,
      });
      await api.deliverRefundAction(draft.id);
      qc.invalidateQueries({ queryKey: ["refund-actions"] });
      toast(`Saved to your Gmail drafts — review and send it yourself`);
      onClose();
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setDelivering(false);
    }
  };

  const footer = (
    <>
      <Button variant="ghost" onClick={onClose}>Close</Button>
      <Button onClick={copy} icon={<Icon.receipt size={14} />} disabled={!draft}>Copy</Button>
      <Button variant="primary" onClick={approveAndCancel} disabled={!draft || saving}>
        {saving ? "Saving…" : "Approve & cancel"}
      </Button>
    </>
  );

  return (
    <Modal title={`Draft ${action} email — ${sub.vendor}`} onClose={onClose} footer={footer} width={560}>
      <div className="modal-body">
        <div className="tabs">
          <button className={`tab ${action === "cancel" ? "active" : ""}`} onClick={() => setAction("cancel")}>
            Cancel
          </button>
          <button className={`tab ${action === "refund" ? "active" : ""}`} onClick={() => setAction("refund")}>
            Request refund
          </button>
        </div>

        <div
          style={{
            display: "flex",
            gap: 9,
            alignItems: "center",
            fontSize: 12,
            color: "var(--text-muted)",
            background: "var(--primary-soft)",
            border: "1px solid var(--border)",
            borderRadius: "var(--r-sm)",
            padding: "9px 11px",
          }}
        >
          <Icon.lock size={14} />
          This is a draft. Nothing is sent — review it, copy it, or save it to your Gmail drafts
          once n8n is connected.
        </div>

        {err ? <div className="error-banner" style={{ margin: 0 }}>{err}</div> : null}

        {loading ? (
          <div className="loading" style={{ padding: 30 }}>
            <div className="spinner" />
            Writing your draft…
          </div>
        ) : draft ? (
          <>
            <div className="field">
              <label>To</label>
              <input
                className="input"
                placeholder="support@vendor.com"
                value={draft.recipient || ""}
                onChange={(e) => setDraft({ ...draft, recipient: e.target.value })}
              />
            </div>
            <div className="field">
              <label>Subject</label>
              <input
                className="input"
                value={draft.subject}
                onChange={(e) => setDraft({ ...draft, subject: e.target.value })}
              />
            </div>
            <div className="field">
              <label>Message</label>
              <textarea
                className="input"
                style={{ minHeight: 190, resize: "vertical", lineHeight: 1.55 }}
                value={draft.email_draft}
                onChange={(e) => setDraft({ ...draft, email_draft: e.target.value })}
              />
            </div>
            <button
              className="btn"
              style={{ justifyContent: "center" }}
              onClick={saveToGmail}
              disabled={!n8nReady || delivering}
              title={n8nReady ? "Create a Gmail draft via n8n" : "Connect n8n to enable (see /n8n/README.md)"}
            >
              <Icon.mail size={14} />{" "}
              {delivering
                ? "Saving…"
                : n8nReady
                ? "Save to Gmail drafts"
                : "Save to Gmail drafts (connect n8n)"}
            </button>
          </>
        ) : null}
      </div>
    </Modal>
  );
}
