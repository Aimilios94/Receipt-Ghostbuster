import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api.js";
import { money, monthLabel, currentMonth, latestMonth } from "../lib/format.js";
import { Card, Loading, ErrorBanner, Button } from "../components/ui.jsx";
import { Icon } from "../components/icons.jsx";
import { CategoryBars } from "../components/sections.jsx";
import { useToast } from "../components/toast.jsx";

// Build the last 6 month options for the picker.
function recentMonths(n = 6) {
  const out = [];
  const d = new Date();
  for (let i = 0; i < n; i++) {
    const m = new Date(d.getFullYear(), d.getMonth() - i, 1);
    out.push(`${m.getFullYear()}-${String(m.getMonth() + 1).padStart(2, "0")}`);
  }
  return out;
}

export default function MonthlyClose() {
  const [month, setMonth] = useState(currentMonth());
  const [picked, setPicked] = useState(false);
  const toast = useToast();

  // Default to the latest month that has data (until the user picks one).
  const { data: expenses } = useQuery({ queryKey: ["expenses"], queryFn: () => api.listExpenses() });
  useEffect(() => {
    if (!picked && expenses?.length) {
      const m = latestMonth(expenses);
      if (m) setMonth(m);
    }
  }, [expenses, picked]);

  const { data: close, isLoading, error } = useQuery({
    queryKey: ["close", month],
    queryFn: () => api.close(month),
  });

  const ready = close && close.unreconciled_count === 0;

  return (
    <div className="rise">
      <div className="page-head">
        <div>
          <h1 className="page-title">Monthly close</h1>
          <div className="page-sub">Lock a month's totals and produce a close summary.</div>
        </div>
        <div className="head-actions">
          <select
            className="select"
            style={{ width: 170 }}
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
        </div>
      </div>

      <ErrorBanner error={error} />

      {isLoading ? (
        <Loading />
      ) : (
        <>
          <div className="grid grid-stats" style={{ marginBottom: 18 }}>
            <SummaryStat label="Money out" value={money(close.total_out)} />
            <SummaryStat label="Money in" value={money(close.total_in)} />
            <SummaryStat label="Net" value={money(close.net)} tone={close.net >= 0 ? "green" : "red"} />
            <SummaryStat label="VAT paid" value={money(close.vat_owed)} />
          </div>

          <div className="grid grid-2" style={{ marginBottom: 18 }}>
            <Card className="card-pad">
              <div className="card-head">
                <div className="card-title">By category</div>
              </div>
              <CategoryBars byCategory={close.by_category} total={close.total_out} />
            </Card>

            <Card className="card-pad">
              <div className="card-head">
                <div className="card-title">Cash flow (bank)</div>
                <div className="card-desc">From your imported statement.</div>
              </div>
              <div className="check">
                <span className="ctext">Bank money in</span>
                <span className="cnote num" style={{ color: "var(--green)" }}>{money(close.bank_in)}</span>
              </div>
              <div className="check">
                <span className="ctext">Bank money out</span>
                <span className="cnote num">{money(close.bank_out)}</span>
              </div>
              <div className="check">
                <span className="ctext">Net cash flow</span>
                <span className="cnote num" style={{ color: close.net_cash_flow >= 0 ? "var(--green)" : "var(--red)" }}>
                  {money(close.net_cash_flow)}
                </span>
              </div>
              <div className="check">
                <span className="ctext">Unreconciled card expenses</span>
                <span className={`cnote num ${close.unreconciled_count ? "warn" : ""}`}>
                  {close.unreconciled_count}
                </span>
              </div>
            </Card>
          </div>

          <Card className="card-pad" style={{ maxWidth: 560 }}>
            <div className="card-head">
              <div>
                <div className="card-title">Close {monthLabel(month)}</div>
                <div className="card-desc">
                  {ready
                    ? "Everything reconciles. You're clear to lock this month."
                    : `${close.unreconciled_count} card expense${close.unreconciled_count > 1 ? "s" : ""} still unreconciled — resolve them first for a clean close.`}
                </div>
              </div>
            </div>
            <Button
              variant={ready ? "primary" : ""}
              style={{ width: "100%", justifyContent: "center" }}
              onClick={() =>
                toast(
                  ready
                    ? `${monthLabel(month)} closed · ${money(close.total_out)} out`
                    : "Resolve open exceptions before closing",
                  ready ? "ok" : "err"
                )
              }
            >
              <Icon.lock size={14} /> {ready ? `Close ${monthLabel(month)}` : "Not ready to close"}
            </Button>
          </Card>
        </>
      )}
    </div>
  );
}

function SummaryStat({ label, value, tone }) {
  return (
    <Card className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value num" style={tone ? { color: `var(--${tone})` } : undefined}>
        {value}
      </div>
    </Card>
  );
}
