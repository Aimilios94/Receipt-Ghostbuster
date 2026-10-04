import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api.js";
import { monthLabel, currentMonth, latestMonth } from "../lib/format.js";
import { Card, Loading, ErrorBanner, Empty, Button } from "../components/ui.jsx";
import { Icon } from "../components/icons.jsx";
import { ExceptionItem, flattenExceptions } from "../components/sections.jsx";
import ImportBankModal from "../components/ImportBankModal.jsx";
import { useToast } from "../components/toast.jsx";

const GROUPS = [
  { key: "unmatched_bank", title: "Bank payments with no receipt" },
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
  const [running, setRunning] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [month, setMonth] = useState(currentMonth());
  const [picked, setPicked] = useState(false);

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

  const counts = data?.counts || {};
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const all = flattenExceptions(data);

  const run = async () => {
    setRunning(true);
    try {
      const res = await api.reconcile();
      ["exceptions", "expenses", "close", "review-queue"].forEach((k) =>
        qc.invalidateQueries({ queryKey: [k] })
      );
      toast(`Matched ${res.matched} · ${res.unmatched_expenses} expenses still open`);
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setRunning(false);
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
                  <ExceptionItem key={i} type={x.type} data={x.data} />
                ))}
              </Card>
            );
          })}
        </>
      )}

      {showImport && <ImportBankModal onClose={() => setShowImport(false)} />}
    </div>
  );
}
