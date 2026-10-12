import { useState, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api.js";
import { money } from "../lib/format.js";
import { Card, Loading, ErrorBanner, Button } from "../components/ui.jsx";
import { Icon } from "../components/icons.jsx";
import { LedgerTable } from "../components/sections.jsx";
import AddExpenseModal from "../components/AddExpenseModal.jsx";
import DrillModal from "../components/DrillModal.jsx";
import { useToast } from "../components/toast.jsx";

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
  { key: "duplicates", label: "Possible duplicates" },
];

// Same key the backend uses to flag duplicates: vendor + amount + date.
function duplicateKey(e) {
  return `${(e.vendor || "").trim().toLowerCase()}|${Number(e.amount || 0).toFixed(2)}|${(e.expense_date || "").slice(0, 10)}`;
}

export default function Ledger() {
  const [searchParams] = useSearchParams();
  const [source, setSource] = useState("all");
  const [status, setStatus] = useState(searchParams.get("view") === "duplicates" ? "duplicates" : "all");
  const [category, setCategory] = useState("all");
  const [showAdd, setShowAdd] = useState(false);
  const [vatDrill, setVatDrill] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const qc = useQueryClient();
  const toast = useToast();

  const { data, isLoading, error } = useQuery({ queryKey: ["expenses"], queryFn: () => api.listExpenses() });
  const { data: categories } = useQuery({ queryKey: ["categories"], queryFn: api.categories });

  const expenses = data || [];

  // Rows that share vendor + amount + date with at least one other row.
  const duplicateIds = useMemo(() => {
    const groups = {};
    for (const e of expenses) {
      const k = duplicateKey(e);
      (groups[k] = groups[k] || []).push(e.id);
    }
    const ids = new Set();
    Object.values(groups).forEach((g) => {
      if (g.length > 1) g.forEach((id) => ids.add(id));
    });
    return ids;
  }, [expenses]);

  const filtered = useMemo(() => {
    return expenses.filter((e) => {
      if (source !== "all" && e.source !== source) return false;
      if (category !== "all" && e.category !== category) return false;
      if (status === "reconciled" && !(e.reconciled || e.matched_transaction_id)) return false;
      if (status === "unmatched" && (e.reconciled || e.matched_transaction_id || e.source === "cash"))
        return false;
      if (status === "pending_review" && e.status !== "pending_review") return false;
      if (status === "duplicates" && !duplicateIds.has(e.id)) return false;
      return true;
    });
  }, [expenses, source, category, status, duplicateIds]);

  const totalShown = filtered.reduce((sum, e) => sum + Number(e.amount || 0), 0);
  const vatShown = filtered.reduce((sum, e) => sum + Number(e.vat_amount || 0), 0);

  const deleteOne = async (exp) => {
    if (!window.confirm(`Delete "${exp.vendor || "this entry"}" (${money(exp.amount)})? This can't be undone.`))
      return;
    setBusyId(exp.id);
    try {
      await api.deleteExpense(exp.id);
      ["expenses", "exceptions", "close", "review-queue"].forEach((k) =>
        qc.invalidateQueries({ queryKey: [k] })
      );
      toast("Entry deleted");
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusyId(null);
    }
  };

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
            <LedgerTable expenses={filtered} onDelete={deleteOne} busyId={busyId} duplicateIds={duplicateIds} />
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "13px 18px",
                borderTop: "1px solid var(--border)",
                fontSize: 13,
                color: "var(--text-muted)",
              }}
            >
              <span>{filtered.length} of {expenses.length} entries</span>
              <span style={{ display: "flex", alignItems: "center", gap: 18 }}>
                <button
                  type="button"
                  className="vat-total-btn"
                  onClick={() => setVatDrill(true)}
                  title="See VAT broken down by rate"
                >
                  VAT <span className="num">{money(vatShown)}</span>
                </button>
                <span className="num" style={{ color: "var(--text)", fontWeight: 560 }}>{money(totalShown)}</span>
              </span>
            </div>
          </>
        )}
      </Card>

      {showAdd && <AddExpenseModal onClose={() => setShowAdd(false)} defaultTab="manual" defaultSource="cash" />}
      {vatDrill && (
        <DrillModal
          title="VAT by rate"
          subtitle="VAT across the entries shown, grouped by rate."
          expenses={filtered.filter((e) => e.vat_amount)}
          mode="vat"
          onClose={() => setVatDrill(false)}
        />
      )}
    </div>
  );
}
