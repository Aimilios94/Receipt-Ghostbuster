import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api.js";
import { money } from "../lib/format.js";
import { Card, Loading, ErrorBanner, Button } from "../components/ui.jsx";
import { Icon } from "../components/icons.jsx";
import { LedgerTable } from "../components/sections.jsx";
import AddExpenseModal from "../components/AddExpenseModal.jsx";

const SOURCE_FILTERS = [
  { key: "all", label: "All" },
  { key: "card", label: "Card" },
  { key: "cash", label: "Cash" },
];
const STATUS_FILTERS = [
  { key: "all", label: "All status" },
  { key: "reconciled", label: "Reconciled" },
  { key: "unmatched", label: "Unmatched" },
  { key: "pending_review", label: "Needs review" },
];

export default function Ledger() {
  const [source, setSource] = useState("all");
  const [status, setStatus] = useState("all");
  const [category, setCategory] = useState("all");
  const [showAdd, setShowAdd] = useState(false);

  const { data, isLoading, error } = useQuery({ queryKey: ["expenses"], queryFn: () => api.listExpenses() });
  const { data: categories } = useQuery({ queryKey: ["categories"], queryFn: api.categories });

  const expenses = data || [];

  const filtered = useMemo(() => {
    return expenses.filter((e) => {
      if (source !== "all" && e.source !== source) return false;
      if (category !== "all" && e.category !== category) return false;
      if (status === "reconciled" && !(e.reconciled || e.matched_transaction_id)) return false;
      if (status === "unmatched" && (e.reconciled || e.matched_transaction_id || e.source === "cash"))
        return false;
      if (status === "pending_review" && e.status !== "pending_review") return false;
      return true;
    });
  }, [expenses, source, category, status]);

  const totalShown = filtered.reduce((sum, e) => sum + Number(e.amount || 0), 0);

  return (
    <div className="rise">
      <div className="page-head">
        <div>
          <h1 className="page-title">Ledger</h1>
          <div className="page-sub">
            Every entry, from receipts and cash alike. All your totals are calculated from here.
          </div>
        </div>
        <div className="head-actions">
          <Button variant="primary" icon={<Icon.plus size={15} />} onClick={() => setShowAdd(true)}>
            Add expense
          </Button>
        </div>
      </div>

      <ErrorBanner error={error} />

      <div className="filters">
        {SOURCE_FILTERS.map((f) => (
          <button
            key={f.key}
            className={`chip ${source === f.key ? "active" : ""}`}
            onClick={() => setSource(f.key)}
          >
            {f.label}
          </button>
        ))}
        <span style={{ width: 1, height: 20, background: "var(--border)" }} />
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.key}
            className={`chip ${status === f.key ? "active" : ""}`}
            onClick={() => setStatus(f.key)}
          >
            {f.label}
          </button>
        ))}
        <select
          className="select"
          style={{ width: 180, marginLeft: "auto" }}
          value={category}
          onChange={(e) => setCategory(e.target.value)}
        >
          <option value="all">All categories</option>
          {(categories || []).map((c) => (
            <option key={c.id} value={c.name}>
              {c.name}
            </option>
          ))}
        </select>
      </div>

      <Card>
        {isLoading ? (
          <Loading />
        ) : (
          <>
            <LedgerTable expenses={filtered} />
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                padding: "13px 18px",
                borderTop: "1px solid var(--border)",
                fontSize: 13,
                color: "var(--text-muted)",
              }}
            >
              <span>{filtered.length} of {expenses.length} entries</span>
              <span className="num" style={{ color: "var(--text)" }}>{money(totalShown)}</span>
            </div>
          </>
        )}
      </Card>

      {showAdd && <AddExpenseModal onClose={() => setShowAdd(false)} defaultTab="manual" defaultSource="cash" />}
    </div>
  );
}
