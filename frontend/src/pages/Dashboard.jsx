import { useState, useMemo } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api.js";
import { money, monthLabel, currentMonth, latestMonth, pct } from "../lib/format.js";
import { Card, Button, Loading, ErrorBanner, Empty } from "../components/ui.jsx";
import { Icon } from "../components/icons.jsx";
import {
  CategoryBars,
  ReviewItem,
  ExceptionItem,
  flattenExceptions,
  LedgerTable,
} from "../components/sections.jsx";
import AddExpenseModal from "../components/AddExpenseModal.jsx";
import ImportBankModal from "../components/ImportBankModal.jsx";
import { useToast } from "../components/toast.jsx";

export default function Dashboard() {
  const [modal, setModal] = useState(null); // 'add' | 'import' | null
  const [busyId, setBusyId] = useState(null);
  const qc = useQueryClient();
  const toast = useToast();

  const expQ = useQuery({ queryKey: ["expenses"], queryFn: () => api.listExpenses() });
  const reviewQ = useQuery({ queryKey: ["review-queue"], queryFn: api.reviewQueue });

  const expenses = expQ.data || [];
  // Open on the latest month that has data, not an empty current month.
  const month = latestMonth(expenses) || currentMonth();
  const closeQ = useQuery({ queryKey: ["close", month], queryFn: () => api.close(month) });
  // Exceptions are scoped to the same month so older bank history (Refund
  // Hunter) doesn't inflate this month's "needs attention".
  const excQ = useQuery({ queryKey: ["exceptions", month], queryFn: () => api.exceptions(month) });

  const close = closeQ.data;
  const review = reviewQ.data || [];
  const excList = flattenExceptions(excQ.data);

  // Derived stats from the ledger (counts the close endpoint doesn't give us).
  const stats = useMemo(() => {
    const cashCount = expenses.filter((e) => e.source === "cash").length;
    const eligible = expenses.filter((e) => e.source !== "cash" && e.status === "posted");
    const reconciled = eligible.filter((e) => e.reconciled || e.matched_transaction_id);
    const rates = [...new Set(expenses.map((e) => e.vat_rate).filter(Boolean))].sort((a, b) => b - a);
    return {
      cashCount,
      eligible: eligible.length,
      reconciled: reconciled.length,
      rates,
    };
  }, [expenses]);

  const postReview = async (exp, patch) => {
    setBusyId(exp.id);
    try {
      await api.confirmExpense(exp.id, patch);
      ["review-queue", "expenses", "exceptions", "close"].forEach((k) =>
        qc.invalidateQueries({ queryKey: [k] })
      );
      toast(`Posted ${patch?.vendor || exp.vendor || "expense"}`);
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusyId(null);
    }
  };

  const discardReview = async (exp) => {
    setBusyId(exp.id);
    try {
      await api.deleteExpense(exp.id);
      ["review-queue", "expenses", "exceptions", "close"].forEach((k) =>
        qc.invalidateQueries({ queryKey: [k] })
      );
      toast("Discarded");
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusyId(null);
    }
  };

  if (closeQ.isLoading && expQ.isLoading) return <Loading label="Loading your month…" />;

  const attention = review.length + excList.length;
  const totalOut = close?.total_out || 0;

  return (
    <div className="rise">
      {/* ---------- Header ---------- */}
      <div className="page-head">
        <div>
          <div className="page-title-row">
            <h1 className="page-title">{monthLabel(month)}</h1>
            <span className="pill-open">
              <Icon.lock size={11} /> Open
            </span>
          </div>
          <div className="page-sub">
            {close?.expense_count ?? expenses.length} expenses
            {close?.bank_out ? " · bank statement imported" : ""}
            {attention ? ` · ${attention} item${attention > 1 ? "s" : ""} need your attention` : " · all clear"}
          </div>
        </div>
        <div className="head-actions">
          <Button icon={<Icon.upload size={15} />} onClick={() => setModal("import")}>
            Import bank statement
          </Button>
          <Button variant="primary" icon={<Icon.plus size={15} />} onClick={() => setModal("add")}>
            Add expense
          </Button>
        </div>
      </div>

      <ErrorBanner error={closeQ.error || expQ.error} />

      {/* ---------- Stat cards ---------- */}
      <div className="grid grid-stats" style={{ marginBottom: 18 }}>
        <Card className="stat">
          <div className="stat-label">Total spent</div>
          <div className="stat-value num">{money(totalOut)}</div>
          <div className="stat-foot">
            {close?.expense_count ?? expenses.length} expenses, {stats.cashCount} paid in cash
          </div>
        </Card>

        <Card className="stat">
          <div className="stat-label">VAT paid</div>
          <div className="stat-value num">{money(close?.vat_owed || 0)}</div>
          <div className="stat-foot">
            {stats.rates.length ? `At ${stats.rates.map((r) => `${r}%`).join(", ")} rates` : "Across your receipts"}
          </div>
        </Card>

        <CardSplit close={close} />

        <Card className="stat">
          <div className="stat-label">Reconciled</div>
          <div className="stat-value num">
            {stats.reconciled} <span style={{ color: "var(--text-dim)", fontWeight: 400 }}>of {stats.eligible}</span>
          </div>
          <div className="progress">
            <span style={{ width: `${pct(stats.reconciled, stats.eligible) || 0}%` }} />
          </div>
          <div className="stat-foot">Card expenses matched to your bank. Cash is left out.</div>
        </Card>
      </div>

      {/* ---------- Row: category + review ---------- */}
      <div className="grid grid-2" style={{ marginBottom: 18 }}>
        <Card className="card-pad">
          <div className="card-head">
            <div>
              <div className="card-title">Spending by category</div>
              <div className="card-desc">Share of this month's total</div>
            </div>
          </div>
          <CategoryBars byCategory={close?.by_category} total={totalOut} limit={7} />
        </Card>

        <Card className="card-pad">
          <div className="card-head">
            <div>
              <div className="card-title">Review queue</div>
              <div className="card-desc">
                Receipts we couldn't read with confidence. Nothing posts until you check it.
              </div>
            </div>
            {review.length ? <span className="nav-count">{review.length}</span> : null}
          </div>
          {review.length ? (
            review.slice(0, 3).map((e) => (
              <ReviewItem
                key={e.id}
                expense={e}
                busy={busyId === e.id}
                onPost={postReview}
                onDiscard={discardReview}
              />
            ))
          ) : (
            <Empty icon={<Icon.check size={26} />}>Nothing waiting. Every receipt is posted.</Empty>
          )}
          {review.length > 3 ? (
            <div style={{ marginTop: 12, textAlign: "center" }}>
              <Link to="/review" className="btn btn-sm btn-ghost">
                View all {review.length} →
              </Link>
            </div>
          ) : null}
        </Card>
      </div>

      {/* ---------- Row: exceptions + close ---------- */}
      <div className="grid grid-2" style={{ marginBottom: 18 }}>
        <Card className="card-pad">
          <div className="card-head">
            <div>
              <div className="card-title">Reconciliation exceptions</div>
              <div className="card-desc">Card expenses that don't line up with your imported bank statement.</div>
            </div>
            {excList.length ? <span className="tag-open">{excList.length} open</span> : null}
          </div>
          {excList.length ? (
            excList.slice(0, 4).map((x, i) => <ExceptionItem key={i} type={x.type} data={x.data} />)
          ) : (
            <Empty icon={<Icon.check size={26} />}>Everything reconciles. No exceptions.</Empty>
          )}
          {excList.length > 4 ? (
            <div style={{ marginTop: 12, textAlign: "center" }}>
              <Link to="/reconciliation" className="btn btn-sm btn-ghost">
                View all {excList.length} →
              </Link>
            </div>
          ) : null}
        </Card>

        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <CloseChecklist close={close} reviewCount={review.length} excCount={excList.length} />
          <RecurringPreview />
        </div>
      </div>

      {/* ---------- Ledger preview ---------- */}
      <Card className="card-pad">
        <div className="card-head">
          <div>
            <div className="card-title">Ledger</div>
            <div className="card-desc">Latest entries. Every total on this page is calculated from here.</div>
          </div>
          <Link to="/ledger" className="btn btn-sm">
            Open ledger →
          </Link>
        </div>
        <LedgerTable expenses={expenses.slice(0, 5)} />
      </Card>

      {modal === "add" && <AddExpenseModal onClose={() => setModal(null)} />}
      {modal === "import" && <ImportBankModal onClose={() => setModal(null)} />}
    </div>
  );
}

/* ---------- Card: card vs cash split ---------- */
function CardSplit({ close }) {
  const bySource = close?.by_source || {};
  const card = bySource.card || 0;
  const cash = bySource.cash || 0;
  const bank = bySource.bank || 0;
  const total = card + cash + bank || 1;
  return (
    <Card className="stat">
      <div className="stat-label">Card and cash</div>
      <div className="splitbar">
        <span style={{ width: `${(card / total) * 100}%`, background: "var(--primary)" }} />
        <span style={{ width: `${(cash / total) * 100}%`, background: "var(--text-dim)" }} />
      </div>
      <div className="legend" style={{ flexDirection: "column", gap: 7 }}>
        <span className="row">
          <span className="dot" style={{ background: "var(--primary)" }} /> Card <b className="num">{money(card)}</b>
        </span>
        <span className="row">
          <span className="dot" style={{ background: "var(--text-dim)" }} /> Cash <b className="num">{money(cash)}</b>
        </span>
      </div>
    </Card>
  );
}

/* ---------- Monthly close checklist ---------- */
function CloseChecklist({ close, reviewCount, excCount }) {
  const items = [
    { label: "Receipts captured", done: true, note: `${close?.expense_count ?? 0} expenses` },
    {
      label: "Review queue cleared",
      done: reviewCount === 0,
      note: reviewCount ? `${reviewCount} left` : "done",
    },
    { label: "Bank statement imported", done: (close?.bank_out || close?.bank_in) ? true : false, note: close?.bank_out ? "imported" : "not yet" },
    {
      label: "Exceptions resolved",
      done: excCount === 0,
      note: excCount ? `${excCount} open` : "done",
    },
  ];
  const ready = items.every((i) => i.done);
  return (
    <Card className="card-pad">
      <div className="card-head">
        <div>
          <div className="card-title">Monthly close</div>
          <div className="card-desc">Lock this month's totals and create a close summary.</div>
        </div>
      </div>
      {items.map((it) => (
        <div className="check" key={it.label}>
          <span className={`cbox ${it.done ? "done" : "todo"}`}>
            {it.done ? <Icon.check size={13} /> : null}
          </span>
          <span className="ctext">{it.label}</span>
          <span className={`cnote ${!it.done ? "warn" : ""}`}>{it.note}</span>
        </div>
      ))}
      <div style={{ marginTop: 14 }}>
        <Link
          to="/close"
          className={`btn ${ready ? "btn-primary" : ""}`}
          style={{ width: "100%", justifyContent: "center" }}
        >
          <Icon.lock size={14} /> {ready ? "Close this month" : "Review before closing…"}
        </Link>
      </div>
    </Card>
  );
}

/* ---------- Recurring charges (Phase 2 — real data) ---------- */
const CADENCE_SHORT = { weekly: "a week", monthly: "a month", quarterly: "a quarter", yearly: "a year" };

function RecurringPreview() {
  const { data } = useQuery({ queryKey: ["subscriptions"], queryFn: api.listSubscriptions });
  const subs = (data || []).filter((s) => s.status !== "cancelled");
  const rows = subs.slice(0, 4);
  return (
    <Card className="card-pad">
      <div className="card-head">
        <div>
          <div className="card-title">Recurring charges</div>
          <div className="card-desc">Subscriptions found across your bank and ledger.</div>
        </div>
        <span className="badge badge-primary">Refund Hunter</span>
      </div>
      {rows.length ? (
        rows.map((s) => (
          <div className="rec" key={s.id}>
            <div>
              <div className="rec-name">{s.vendor}</div>
              {s.stale ? <div className="rec-warn">Not seen in {s.days_since_last} days</div> : null}
            </div>
            <div className="rec-amt num">
              {money(s.amount)} {CADENCE_SHORT[s.cadence] || ""}
            </div>
          </div>
        ))
      ) : (
        <Empty>No subscriptions detected yet.</Empty>
      )}
      <div style={{ marginTop: 14 }}>
        <Link to="/refunds" className="btn" style={{ width: "100%", justifyContent: "center" }}>
          <Icon.refund size={14} /> Open Refund Hunter
        </Link>
      </div>
    </Card>
  );
}
