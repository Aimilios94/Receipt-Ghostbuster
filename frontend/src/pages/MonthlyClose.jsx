import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, readOnlyProps } from "../lib/api.js";
import { money, monthLabel } from "../lib/format.js";
import { MonthPicker, useMonth } from "../lib/month.jsx";
import { Card, Loading, ErrorBanner, Button } from "../components/ui.jsx";
import { Icon } from "../components/icons.jsx";
import { CategoryBars } from "../components/sections.jsx";
import { useToast } from "../components/toast.jsx";

export default function MonthlyClose() {
  const { month } = useMonth();
  const toast = useToast();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);

  const { data: close, isLoading, error } = useQuery({
    queryKey: ["close", month],
    queryFn: () => api.close(month),
  });

  const ready = close && close.unreconciled_count === 0;
  const saved = close?.saved_close;
  const changed = close?.changed_since_close || [];
  const fmtValue = (c, v) =>
    v == null ? "—" : /count/.test(c.field) ? String(v) : money(v);
  const closedOn = saved
    ? new Date(saved.closed_at).toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })
    : "";

  const run = async (fn, okText) => {
    setBusy(true);
    try {
      await fn();
      qc.invalidateQueries({ queryKey: ["close"] });
      toast(okText);
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusy(false);
    }
  };
  const saveClose = () =>
    run(() => api.saveClose(month), `${monthLabel(month)} closed · ${money(close.total_out)} out, VAT ${money(close.vat_owed)}`);
  const reopen = () => {
    if (!window.confirm(`Reopen ${monthLabel(month)}? Its close record is removed; no expense changes.`)) return;
    run(() => api.reopenClose(month), `${monthLabel(month)} reopened`);
  };
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
                <div className="card-title">
                  {saved ? `${monthLabel(month)} is closed` : `Close ${monthLabel(month)}`}
                </div>
                <div className="card-desc">
                  {saved
                    ? `Closed on ${closedOn} with ${money(saved.summary.total_out)} out and VAT ${money(saved.summary.vat_owed)}.`
                    : ready
                    ? readyText
                    : `${close.unreconciled_count} card expense${close.unreconciled_count > 1 ? "s" : ""} still unreconciled — resolve them first for a clean close.`}
                </div>
              </div>
            </div>
            {saved && changed.length ? (
              <div className="close-changed" role="status">
                <b>Changed since you closed it:</b>
                <ul>
                  {changed.map((c) => (
                    <li key={c.field}>
                      {c.label}: <span className="num">{fmtValue(c, c.saved)}</span> →{" "}
                      <span className="num">{fmtValue(c, c.now)}</span>
                    </li>
                  ))}
                </ul>
                Close it again to record the new figures, or undo the change.
              </div>
            ) : saved ? (
              <p className="card-desc" style={{ marginBottom: 10 }}>Nothing has changed since then.</p>
            ) : null}
            {saved ? (
              <div style={{ display: "flex", gap: 8 }}>
                {changed.length ? (
                  <Button variant="primary" disabled={busy || !ready} onClick={saveClose} style={{ flex: 1, justifyContent: "center" }} {...readOnlyProps}>
                    <Icon.check size={14} /> Close again
                  </Button>
                ) : null}
                <Button disabled={busy} onClick={reopen} style={{ flex: 1, justifyContent: "center" }} {...readOnlyProps}>
                  Reopen {monthLabel(month)}
                </Button>
              </div>
            ) : (
              <Button
                variant={ready ? "primary" : ""}
                style={{ width: "100%", justifyContent: "center" }}
                disabled={busy}
                onClick={() => (ready ? saveClose() : toast("Resolve open exceptions before closing", "err"))}
                {...readOnlyProps}
              >
                <Icon.check size={14} /> {ready ? `Close ${monthLabel(month)}` : "Not ready to close"}
              </Button>
            )}
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
