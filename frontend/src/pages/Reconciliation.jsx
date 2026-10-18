import { useState, useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api.js";
import { monthLabel, currentMonth, latestMonth } from "../lib/format.js";
import { Card, Loading, ErrorBanner, Empty, Button } from "../components/ui.jsx";
import { Icon } from "../components/icons.jsx";
import { ExceptionItem, BankStatementAlert, flattenExceptions } from "../components/sections.jsx";
import ImportBankModal from "../components/ImportBankModal.jsx";
import ExpenseDetailModal from "../components/ExpenseDetailModal.jsx";
import StatementDetailModal from "../components/StatementDetailModal.jsx";
import ReconcileResultModal from "../components/ReconcileResultModal.jsx";
import { useToast } from "../components/toast.jsx";
import { useSeen } from "../lib/useSeen.js";

// unmatched_bank is intentionally not here — those are collapsed into one row per
// statement (see the "Imported statements" card below / the Bank statements page).
const GROUPS = [
  { key: "unmatched_expenses", title: "Card expenses with no bank match" },
  { key: "duplicates", title: "Possible duplicates" },
  { key: "amount_mismatch", title: "Amount differences" },
  { key: "missing_vat", title: "Missing VAT" },
];

function recentMonths(n = 6) {
  const out = [];
  const d = new Date();
  for (let i = 0; i < n; i++) {
    const m = new Date(d.getFullYear(), d.getMonth() - i, 1);
    out.push(`${m.getFullYear()}-${String(m.getMonth() + 1).padStart(2, "0")}`);
  }
  return out;
}

export default function Reconciliation() {
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const [running, setRunning] = useState(false);
  const [reconResult, setReconResult] = useState(null);
  const [showImport, setShowImport] = useState(false);
  const [month, setMonth] = useState(currentMonth());
  const [picked, setPicked] = useState(false);
  const [detail, setDetail] = useState(null);

  // Default the picker to the latest month that has expenses.
  const { data: expenses } = useQuery({ queryKey: ["expenses"], queryFn: () => api.listExpenses() });
  useEffect(() => {
    if (!picked && expenses?.length) {
      const m = latestMonth(expenses);
      if (m) setMonth(m);
    }
  }, [expenses, picked]);

  const { data, isLoading, error } = useQuery({
    queryKey: ["exceptions", month],
    queryFn: () => api.exceptions(month),
  });
  const { data: statements } = useQuery({ queryKey: ["statements"], queryFn: api.listStatements });

  const alertStatements = useMemo(
    () =>
      (statements || []).filter(
        (s) =>
          s.needs_receipt_count > 0 &&
          s.period_start &&
          s.period_start.slice(0, 7) <= month &&
          s.period_end.slice(0, 7) >= month
      ),
    [statements, month]
  );
  const stmtIds = useMemo(() => (statements || []).map((s) => s.id), [statements]);
  const { isNew: stmtIsNew, mark: markStmtSeen } = useSeen("rg_seen_statements", stmtIds);
  const [stmtDetailId, setStmtDetailId] = useState(null);
  // Row click = transactions popup in place; "View" = the Bank statements section.
  const openStatement = (s) => {
    markStmtSeen(s.id);
    setStmtDetailId(s.id);
  };
  const viewStatement = (s) => {
    markStmtSeen(s.id);
    navigate("/bank-statements");
  };

  const all = flattenExceptions(data);
  const total = all.length + alertStatements.length;

  const deleteExc = async (exp) => {
    if (!window.confirm(`Delete "${exp.vendor || "this entry"}"? This can't be undone.`)) return;
    try {
      await api.deleteExpense(exp.id);
      ["exceptions", "expenses", "close", "review-queue", "line-items"].forEach((k) =>
        qc.invalidateQueries({ queryKey: [k] })
      );
      toast("Entry deleted");
    } catch (e) {
      toast(e.message, "err");
    }
  };

  const invalidateRecon = () =>
    ["exceptions", "expenses", "close", "review-queue", "statements"].forEach((k) =>
      qc.invalidateQueries({ queryKey: [k] })
    );

  const run = async () => {
    setRunning(true);
    try {
      const res = await api.reconcile();
      invalidateRecon();
      setReconResult(res); // open the results popup
      toast(
        `Matched ${res.newly_matched} new · ${res.unmatched_expenses} expense${res.unmatched_expenses === 1 ? "" : "s"} still open`
      );
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setRunning(false);
    }
  };

  // Open the same match/unmatch view WITHOUT running the auto-matcher, so the user
  // can do (and undo) matches by hand any time.
  const openManual = async () => {
    try {
      setReconResult(await api.reconcileState());
    } catch (e) {
      toast(e.message, "err");
    }
  };

  return (
    <div className="rise">
      <div className="page-head">
        <div>
          <h1 className="page-title">Reconciliation</h1>
          <div className="page-sub">
            Match card expenses to your imported bank statement for {monthLabel(month)}. Cash is
            excluded by design.
          </div>
        </div>
        <div className="head-actions">
          <select
            className="select"
            style={{ width: 160 }}
            value={month}
            onChange={(e) => {
              setPicked(true);
              setMonth(e.target.value);
            }}
          >
            {recentMonths().map((m) => (
              <option key={m} value={m}>
                {monthLabel(m)}
              </option>
            ))}
          </select>
          <Button icon={<Icon.upload size={15} />} onClick={() => setShowImport(true)}>
            Import bank statement
          </Button>
          <Button icon={<Icon.search size={15} />} onClick={openManual}>
            Match manually
          </Button>
          <Button variant="primary" icon={<Icon.reconcile size={15} />} onClick={run} disabled={running}>
            {running ? "Matching…" : "Run reconciliation"}
          </Button>
        </div>
      </div>

      <ErrorBanner error={error} />

      {isLoading ? (
        <Loading />
      ) : total === 0 ? (
        <Card className="card-pad">
          <Empty icon={<Icon.check size={30} />}>
            No open exceptions. Every card expense lines up with the bank.
          </Empty>
        </Card>
      ) : (
        <>
          <div className="page-sub" style={{ marginTop: -14, marginBottom: 18 }}>
            <span className="tag-open">{total} open exception{total > 1 ? "s" : ""}</span>
          </div>
          {alertStatements.length ? (
            <Card className="card-pad" style={{ marginBottom: 18 }}>
              <div className="card-head">
                <div className="card-title">
                  Imported statements{" "}
                  <span style={{ color: "var(--text-dim)" }}>· {alertStatements.length}</span>
                </div>
              </div>
              <div className="card-desc" style={{ marginBottom: 6 }}>
                Each statement's unmatched card payments are grouped here. Open it to see every
                transaction and upload the matching receipts.
              </div>
              {alertStatements.map((s) => (
                <BankStatementAlert
                  key={s.id}
                  statement={s}
                  isNew={stmtIsNew(s.id)}
                  onOpen={openStatement}
                  onView={viewStatement}
                />
              ))}
            </Card>
          ) : null}
          {GROUPS.map((g) => {
            const items = all.filter((x) => x.type === g.key);
            if (!items.length) return null;
            return (
              <Card className="card-pad" key={g.key} style={{ marginBottom: 18 }}>
                <div className="card-head">
                  <div className="card-title">
                    {g.title} <span style={{ color: "var(--text-dim)" }}>· {items.length}</span>
                  </div>
                </div>
                {items.map((x, i) => (
                  <ExceptionItem key={i} type={x.type} data={x.data} onOpenExpense={setDetail} onDelete={deleteExc} />
                ))}
              </Card>
            );
          })}
        </>
      )}

      {showImport && <ImportBankModal onClose={() => setShowImport(false)} />}
      {detail && <ExpenseDetailModal expense={detail} onClose={() => setDetail(null)} />}
      {stmtDetailId && (
        <StatementDetailModal id={stmtDetailId} onClose={() => setStmtDetailId(null)} />
      )}
      {reconResult && (
        <ReconcileResultModal
          initialState={reconResult}
          onChanged={invalidateRecon}
          onClose={() => setReconResult(null)}
        />
      )}
    </div>
  );
}
