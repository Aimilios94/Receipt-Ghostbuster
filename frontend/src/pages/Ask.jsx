import { useState, useRef, useEffect } from "react";
import { api } from "../lib/api.js";
import { money, shortDate } from "../lib/format.js";
import { Card, Button, Modal, ErrorBanner } from "../components/ui.jsx";
import { Icon } from "../components/icons.jsx";
import { ReceiptLightbox } from "../components/ReceiptLightbox.jsx";

// Receipt thumbnails → open the lightbox.
function ReceiptThumbs({ items, onOpen }) {
  return (
    <div className="ask-receipts">
      {items.map((a, k) => (
        <button key={k} type="button" className="ask-receipt" onClick={() => onOpen(a.url)} title={a.label || "Receipt"}>
          <img src={a.url} alt={a.label || "Receipt"} loading="lazy" />
          <span>{a.label || "Receipt"}</span>
        </button>
      ))}
    </div>
  );
}

// Expenses grouped by vendor — compact rows; click a vendor to open a detail popup
// (like the Breakdown popup), so the list stays clean whether a vendor has 1 or many.
function ExpenseGroups({ att, onOpenGroup }) {
  return (
    <div className="ask-attach">
      <div className="ask-attach-head">
        <span>{att.title}</span>
        <span className="bd-section-sub">{att.count} expense{att.count === 1 ? "" : "s"} · total <b className="num">{money(att.total)}</b></span>
      </div>
      <div className="bd-list">
        {(att.groups || []).map((g, i) => (
          <button type="button" className="bd-row" key={i} onClick={() => onOpenGroup(g)} title="See the expenses">
            <span className="bd-name">{g.vendor}</span>
            <span className="bd-count">{g.count}×</span>
            <span className="bd-total num">{money(g.total)}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

// Small popup listing one vendor's expenses (date · category · amount, with a receipt link).
function GroupDetailModal({ group, onClose, onReceipt }) {
  return (
    <Modal title={group.vendor} onClose={onClose} width={440}>
      <div className="modal-body">
        <div className="bd-detail-list">
          {group.items.map((it, i) => (
            <div className="bd-detail-item" key={i}>
              <span className="bd-item-date">{shortDate(it.date)}</span>
              <span className="bd-item-label">
                {it.category}
                {it.has_receipt ? (
                  <button type="button" className="ask-inline-link" onClick={() => onReceipt(it.receipt_url)}>· receipt</button>
                ) : null}
              </span>
              <span className="bd-item-amt num">{money(it.amount)}</span>
            </div>
          ))}
        </div>
        <div className="bd-detail-foot">
          <span>{group.items.length} expense{group.items.length === 1 ? "" : "s"}</span>
          <span>Total <b className="num">{money(group.total)}</b></span>
        </div>
      </div>
    </Modal>
  );
}

function toCsv(columns, rows) {
  const esc = (v) => {
    const s = v == null ? "" : String(v);
    return /[",\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [columns.join(","), ...rows.map((r) => r.map(esc).join(","))].join("\n");
}

// Bank transactions as a table + a Download CSV button (built client-side).
function TxnTable({ att }) {
  const download = () => {
    const blob = new Blob([toCsv(att.columns, att.rows)], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = att.filename || "transactions.csv";
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div className="ask-attach">
      <div className="ask-attach-head">
        <span>{att.title}</span>
        <span className="bd-section-sub">
          out <b className="num">{money(att.total_out)}</b> · in <b className="num">{money(att.total_in)}</b>
          <button type="button" className="btn btn-sm btn-ghost" style={{ marginLeft: 10 }} onClick={download}>
            <Icon.upload size={13} /> Download CSV
          </button>
        </span>
      </div>
      <div style={{ overflowX: "auto", maxHeight: 320, overflowY: "auto" }}>
        <table className="raw-csv-table">
          <thead><tr>{att.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>
            {att.rows.map((r, i) => (
              <tr key={i}>{r.map((c, j) => <td key={j}>{c == null ? "" : String(c)}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Attachments({ atts, onOpen, onOpenGroup }) {
  const receipts = atts.filter((a) => a.type === "receipt");
  return (
    <>
      {receipts.length ? <ReceiptThumbs items={receipts} onOpen={onOpen} /> : null}
      {atts.filter((a) => a.type === "expense_groups").map((a, i) => <ExpenseGroups key={i} att={a} onOpenGroup={onOpenGroup} />)}
      {atts.filter((a) => a.type === "table").map((a, i) => <TxnTable key={i} att={a} />)}
    </>
  );
}

const SUGGESTIONS = [
  "Which day did I spend the most this month?",
  "How much did I spend on Groceries this month?",
  "What are my active subscriptions and their annual cost?",
  "How much did I send to people this month?",
  "How much VAT have I paid this year?",
];

export default function Ask() {
  const [messages, setMessages] = useState([]); // {role, content, tools?}
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [lightbox, setLightbox] = useState(null);
  const [groupDetail, setGroupDetail] = useState(null);
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  const send = async (text) => {
    const q = (text ?? input).trim();
    if (!q || busy) return;
    setErr(null);
    setInput("");
    const history = messages.map((m) => ({ role: m.role, content: m.content }));
    const next = [...messages, { role: "user", content: q }];
    setMessages(next);
    setBusy(true);
    try {
      const res = await api.chat(q, history);
      setMessages([
        ...next,
        {
          role: "assistant",
          content: res.answer || "(no answer)",
          tools: res.used_tools || [],
          attachments: res.attachments || [],
        },
      ]);
    } catch (e) {
      setErr(e.message);
      setMessages(next); // keep the question; let them retry
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rise">
      <div className="page-head">
        <div>
          <h1 className="page-title">Ask</h1>
          <div className="page-sub">
            Ask about your ledger in plain language. Every number is computed in code from your
            data — the assistant only picks the right calculation, it never does the math itself.
          </div>
        </div>
      </div>

      <ErrorBanner error={err} />

      <Card className="card-pad">
        {messages.length === 0 ? (
          <div className="ask-empty">
            <Icon.chat size={26} />
            <p>Try one of these:</p>
            <div className="ask-suggestions">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="chip" onClick={() => send(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="ask-thread">
            {messages.map((m, i) => (
              <div key={i} className={`ask-msg ask-${m.role}`}>
                <div className="ask-bubble">{m.content}</div>
                {m.role === "assistant" && m.attachments?.length ? (
                  <Attachments atts={m.attachments} onOpen={setLightbox} onOpenGroup={setGroupDetail} />
                ) : null}
                {m.role === "assistant" && m.tools?.length ? (
                  <div className="ask-tools" title="Analytics functions used to compute the answer">
                    {m.tools.map((t, j) => (
                      <span className="ask-tool" key={j}>{t.name}</span>
                    ))}
                  </div>
                ) : null}
              </div>
            ))}
            {busy ? <div className="ask-msg ask-assistant"><div className="ask-bubble ask-thinking">Thinking…</div></div> : null}
            <div ref={endRef} />
          </div>
        )}

        <form
          className="ask-input-row"
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
        >
          <input
            className="input"
            placeholder="Ask about your spending, VAT, subscriptions, transfers…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={busy}
          />
          <Button variant="primary" icon={<Icon.chat size={15} />} disabled={busy || !input.trim()}>
            {busy ? "…" : "Ask"}
          </Button>
        </form>
      </Card>

      {groupDetail ? (
        <GroupDetailModal group={groupDetail} onClose={() => setGroupDetail(null)} onReceipt={setLightbox} />
      ) : null}
      {lightbox ? <ReceiptLightbox src={lightbox} onClose={() => setLightbox(null)} /> : null}
    </div>
  );
}
