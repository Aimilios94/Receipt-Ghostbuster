import { useState, useRef, useEffect } from "react";
import { api } from "../lib/api.js";
import { money, shortDate } from "../lib/format.js";
import { Card, Button, Modal, ErrorBanner } from "../components/ui.jsx";
import { Icon } from "../components/icons.jsx";
import { ReceiptLightbox } from "../components/ReceiptLightbox.jsx";
import ExpenseDetailModal from "../components/ExpenseDetailModal.jsx";

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

// Small popup listing one vendor's expenses. A row opens its full detail.
function GroupDetailModal({ group, onClose, onReceipt, onOpenExpense }) {
  return (
    <Modal title={group.vendor} onClose={onClose} width={440}>
      <div className="modal-body">
        <div className="bd-detail-list">
          {group.items.map((it, i) => (
            <div className="bd-detail-item" key={i}>
              <span className="bd-item-date">{shortDate(it.date)}</span>
              <span className="bd-item-label">
                {it.id ? (
                  <button type="button" className="ask-inline-link" onClick={() => onOpenExpense(it.id)} title="See the products, VAT and receipt">
                    {it.category}
                  </button>
                ) : it.category}
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

// Expense rows inside a card. Each opens the full detail: products, VAT per rate, receipt.
function ExpenseRows({ expenses, onOpenExpense, amountKey = "amount" }) {
  return expenses.map((e, i) => (
    <button type="button" className="ask-expense" key={e.id || i} onClick={() => onOpenExpense(e.id)} title="See the products, VAT and receipt">
      <span className="ask-expense-name">{e.vendor}</span>
      <span className="ask-expense-amt num">{money(e[amountKey])}</span>
      <span className="ask-expense-meta">
        {shortDate(e.date)} · {e.category}{e.source === "cash" ? " · cash" : ""}
      </span>
    </button>
  ));
}

// Ranked rows with bars: days, categories, vendors, products, people. A row with
// expenses opens to list them, so a long answer starts as a short overview.
function TransactionRows({ transactions }) {
  return transactions.map((t, i) => (
    <div className="ask-expense ask-transaction" key={i}>
      <span className="ask-expense-name">{t.label || "Transfer"}</span>
      <span className="ask-expense-amt num">{money(t.amount)}</span>
      <span className="ask-expense-meta">{shortDate(t.date)}</span>
    </div>
  ));
}

function RankingCard({ att, onOpenExpense }) {
  // A one-row answer ("the busiest day") opens straight away: its expenses are the answer.
  const [open, setOpen] = useState(att.rows.length === 1 && att.rows[0].expenses?.length ? 0 : null);
  const countText = (r) => {
    if (r.count == null) return "";
    if (att.count_unit === "times") return `${r.count}×`;
    const unit = att.count_unit === "transfers" ? "transfer" : "expense";
    return `${r.count} ${unit}${r.count === 1 ? "" : "s"}`;
  };
  return (
    <div className="ask-card">
      <div className="ask-card-head">
        <span className="ask-card-title">{att.title}</span>
        <span className="ask-card-sub">
          {att.subtitle}
          {att.total != null ? <> · total <b className="num">{money(att.total)}</b></> : null}
        </span>
      </div>
      {att.rows.map((r, i) => {
        const hasDetail = r.expenses?.length > 0 || r.transactions?.length > 0;
        const isOpen = open === i;
        const content = (
          <>
            <span className="ask-rank-label" title={r.label}>{r.label}</span>
            <span className="ask-rank-bar"><span className="ask-rank-fill" style={{ width: `${r.bar * 100}%` }} /></span>
            <span className="ask-rank-amt num">{money(r.total)}</span>
            <span className="ask-rank-count">{countText(r)}</span>
            <span className={`ask-rank-chev${isOpen ? " open" : ""}`}>{hasDetail ? "▸" : ""}</span>
          </>
        );
        return (
          <div key={i}>
            {hasDetail ? (
              <button type="button" className="ask-rank-row" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : i)}>
                {content}
              </button>
            ) : (
              <div className="ask-rank-row">{content}</div>
            )}
            {isOpen && hasDetail ? (
              <div className="ask-expenses">
                {r.expenses ? <ExpenseRows expenses={r.expenses} onOpenExpense={onOpenExpense} /> : null}
                {r.transactions ? <TransactionRows transactions={r.transactions} /> : null}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function ExpenseListCard({ att, onOpenExpense }) {
  return (
    <div className="ask-card">
      <div className="ask-card-head">
        <span className="ask-card-title">{att.title}</span>
        {att.subtitle ? <span className="ask-card-sub">{att.subtitle}</span> : null}
      </div>
      <ExpenseRows expenses={att.expenses} onOpenExpense={onOpenExpense} />
      {att.products?.length ? (
        <div className="ask-products">
          {att.products.map((p, i) => (
            <div className="ask-product" key={i}>
              <span className="ask-product-name" title={p.name}>{p.name}</span>
              <span className="num">{money(p.amount)}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function TotalCard({ att, onOpenExpense }) {
  const [open, setOpen] = useState(false);
  const count = att.expenses?.length || 0;
  return (
    <div className="ask-card">
      <div className="ask-card-head">
        <span className="ask-card-title">{att.title}</span>
        <span className="ask-card-sub">{att.subtitle}</span>
      </div>
      <div className="ask-total-value num">{money(att.total)}</div>
      {count ? (
        <>
          <button type="button" className="ask-drill" aria-expanded={open} onClick={() => setOpen(!open)}>
            <span className={`ask-rank-chev${open ? " open" : ""}`}>▸</span> {count} expense{count === 1 ? "" : "s"}
          </button>
          {open ? (
            <div className="ask-expenses">
              <ExpenseRows expenses={att.expenses} onOpenExpense={onOpenExpense} amountKey={att.amount_key || "amount"} />
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function ComparisonCard({ att, onOpenExpense }) {
  const [open, setOpen] = useState(null);
  const delta = Number(att.delta || 0);
  return (
    <div className="ask-card">
      <div className="ask-card-head"><span className="ask-card-title">{att.title}</span></div>
      <div className="ask-compare">
        {[att.a, att.b].map((side, i) => (
          <div key={side.label}>
            <div className="ask-compare-label">{side.label}</div>
            <div className="ask-compare-value num">
              {side.total == null ? <span className="ask-compare-empty">No records</span> : money(side.total)}
            </div>
            {side.expenses?.length ? (
              <button type="button" className="ask-drill" aria-expanded={open === i} onClick={() => setOpen(open === i ? null : i)}>
                <span className={`ask-rank-chev${open === i ? " open" : ""}`}>▸</span> {side.expenses.length} expense{side.expenses.length === 1 ? "" : "s"}
              </button>
            ) : null}
          </div>
        ))}
        {att.delta != null ? (
          <div className={`ask-compare-delta ${delta > 0 ? "up" : delta < 0 ? "down" : ""}`}>
            {delta > 0 ? "+" : delta < 0 ? "−" : ""}{money(Math.abs(delta))}
            {att.pct_change != null ? ` (${att.pct_change > 0 ? "+" : ""}${att.pct_change}%)` : ""}
          </div>
        ) : null}
      </div>
      {open != null ? (
        <div className="ask-expenses ask-compare-rows">
          <ExpenseRows expenses={(open === 0 ? att.a : att.b).expenses} onOpenExpense={onOpenExpense} />
        </div>
      ) : null}
    </div>
  );
}

function Attachments({ atts, onOpen, onOpenGroup, onOpenExpense }) {
  const receipts = atts.filter((a) => a.type === "receipt");
  return (
    <>
      {receipts.length ? <ReceiptThumbs items={receipts} onOpen={onOpen} /> : null}
      {atts.map((a, i) => {
        if (a.type === "ranking") return <RankingCard key={i} att={a} onOpenExpense={onOpenExpense} />;
        if (a.type === "expense_list") return <ExpenseListCard key={i} att={a} onOpenExpense={onOpenExpense} />;
        if (a.type === "comparison") return <ComparisonCard key={i} att={a} onOpenExpense={onOpenExpense} />;
        if (a.type === "total") return <TotalCard key={i} att={a} onOpenExpense={onOpenExpense} />;
        if (a.type === "expense_groups") return <ExpenseGroups key={i} att={a} onOpenGroup={onOpenGroup} />;
        if (a.type === "table") return <TxnTable key={i} att={a} />;
        return null;
      })}
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
  const [expenseDetail, setExpenseDetail] = useState(null);
  const endRef = useRef(null);
  const lastRef = useRef(null);

  // A new answer is read from its first line, so scroll to its start, not its end.
  useEffect(() => {
    const last = messages[messages.length - 1];
    if (last?.role === "assistant" && !busy) {
      lastRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    } else {
      endRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, busy]);

  // Stay available during a conversation, minus what was already asked.
  const asked = new Set(messages.filter((m) => m.role === "user").map((m) => m.content));
  const remaining = SUGGESTIONS.filter((s) => !asked.has(s));

  const openExpense = async (id) => {
    try {
      const expenses = await api.listExpenses();
      const expense = expenses.find((e) => e.id === id);
      if (expense) setExpenseDetail(expense);
    } catch (e) {
      setErr(e.message);
    }
  };

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
              <div
                key={i}
                ref={i === messages.length - 1 ? lastRef : null}
                className={`ask-msg ask-${m.role}${m.attachments?.length ? " ask-with-cards" : ""}`}
              >
                <div className="ask-bubble">{m.content}</div>
                {m.role === "assistant" && m.attachments?.length ? (
                  <Attachments atts={m.attachments} onOpen={setLightbox} onOpenGroup={setGroupDetail} onOpenExpense={openExpense} />
                ) : null}
                {m.role === "assistant" && m.tools?.length ? (
                  <details className="ask-how">
                    <summary>How this was calculated</summary>
                    <div className="ask-tools" title="Analytics functions used to compute the answer">
                      {[...new Set(m.tools.map((t) => t.name))].map((name) => (
                        <span className="ask-tool" key={name}>{name}</span>
                      ))}
                    </div>
                  </details>
                ) : null}
              </div>
            ))}
            {busy ? <div className="ask-msg ask-assistant"><div className="ask-bubble ask-thinking">Thinking…</div></div> : null}
            <div ref={endRef} />
          </div>
        )}

        {messages.length > 0 && remaining.length > 0 ? (
          <div className="ask-suggestions ask-suggestions-compact" aria-label="Suggested questions">
            {remaining.map((s) => (
              <button
                key={s}
                type="button"
                className="chip"
                disabled={busy}
                title={busy ? "Available once this answer arrives" : undefined}
                onClick={() => send(s)}
              >
                {s}
              </button>
            ))}
          </div>
        ) : null}

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
        <GroupDetailModal group={groupDetail} onClose={() => setGroupDetail(null)} onReceipt={setLightbox} onOpenExpense={openExpense} />
      ) : null}
      {expenseDetail ? <ExpenseDetailModal expense={expenseDetail} onClose={() => setExpenseDetail(null)} /> : null}
      {lightbox ? <ReceiptLightbox src={lightbox} onClose={() => setLightbox(null)} /> : null}
    </div>
  );
}
