import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api.js";
import { money, monthLabel } from "../lib/format.js";
import { MonthPicker, useMonth } from "../lib/month.jsx";
import { Card, Loading, ErrorBanner, Button } from "../components/ui.jsx";
import { Icon } from "../components/icons.jsx";
import { CategoryBars } from "../components/sections.jsx";
import { useToast } from "../components/toast.jsx";

export default function MonthlyClose() {
  const { month } = useMonth();
  const toast = useToast();

  const { data: close, isLoading, error } = useQuery({
    queryKey: ["close", month],
    queryFn: () => api.close(month),
  });

  const ready = close && close.unreconciled_count === 0;
  const matched = close?.reconciled_count ?? 0;
  const marked = close?.no_bank_line_count ?? 0;
  const plural = (n, word) => `${n} card expense${n === 1 ? "" : "s"} ${word}`;
  // "Ready" means nothing is left to reconcile. When some rows are only marked
  // paid with another card, say so instead of claiming everything matched the bank.
  const readyText = !close
    ? ""
    : matched + marked === 0
    ? "No card expenses to reconcile. This month is ready to close."
    : marked
    ? `${plural(matched, "matched to the bank")} and ${marked} paid with another card, so nothing is left to reconcile. Ready to close.`
    : "Every card expense is matched to the bank. This month is ready to close.";

  return (
    <div className="rise">
      <div className="page-head">
        <div>
          <h1 className="page-title">Monthly close</h1>
          <div className="page-sub">Check a month's totals and produce a close summary.</div>
        </div>
        <div className="head-actions">
          <MonthPicker />
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
                    ? readyText
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
                    ? `${monthLabel(month)}: ${matched} matched${marked ? `, ${marked} paid with another card` : ""} · ${money(close.total_out)} out. Close records aren't saved yet.`
                    : "Resolve open exceptions before closing",
                  ready ? "ok" : "err"
                )
              }
            >
              <Icon.check size={14} /> {ready ? `Check ${monthLabel(month)}` : "Not ready to close"}
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
