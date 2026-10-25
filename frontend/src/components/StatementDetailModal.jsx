import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api.js";
import { money, shortDate } from "../lib/format.js";
import { Modal, Button, Loading, ErrorBanner } from "./ui.jsx";
import { Icon } from "./icons.jsx";

function periodLabel(s) {
  return s?.period_start ? `${shortDate(s.period_start)} – ${shortDate(s.period_end)}` : "—";
}

// The exact source rows behind the statement — the raw CSV as it was uploaded
// (one column per original header), so the user can confirm values at the source,
// the same way a receipt image can be opened. Only settled rows were imported
// (PENDING/REVERTED are skipped at import), so this shows the statement's stored rows.
function RawCsvTable({ txns }) {
  const { columns, rows } = useMemo(() => {
    const raws = txns.map((t) => t.raw).filter((r) => r && typeof r === "object");
    const cols = [];
    for (const r of raws) {
      for (const k of Object.keys(r)) if (!cols.includes(k)) cols.push(k);
    }
    return { columns: cols, rows: raws };
  }, [txns]);

  if (!rows.length) {
    return (
      <p style={{ fontSize: 13, color: "var(--text-dim)" }}>
        No raw rows stored for this statement.
      </p>
    );
  }
  return (
    <div style={{ overflowX: "auto", maxHeight: 420, overflowY: "auto" }}>
      <table className="raw-csv-table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c}>{r[c] ?? ""}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function status(t) {
  if (t.matched) return { text: "Matched", cls: "tag-done" };
  if (t.no_receipt) return { text: "No receipt", cls: "tag-muted" };
  if (t.needs_receipt) return { text: "Needs receipt", cls: "tag-open" };
  return { text: "Not a purchase", cls: "tag-muted" };
}

// All transactions of one imported statement. Laid out in a responsive multi-column
// grid (not one long vertical list) and scrollable, so a 40-row statement stays on a
// single centered, fully-visible popup.
export default function StatementDetailModal({ id, onClose }) {
  const [showRaw, setShowRaw] = useState(false);
  const { data, isLoading, error } = useQuery({
    queryKey: ["statement-txns", id],
    queryFn: () => api.statementTransactions(id),
  });
  const s = data?.statement;
  const txns = data?.transactions || [];

  return (
    <Modal title={s ? s.filename || "Bank statement" : "Bank statement"} onClose={onClose} width={860}>
      <div className="modal-body">
        <ErrorBanner error={error} />
        {isLoading ? (
          <Loading />
        ) : (
          <>
            {s ? (
              <div className="detail-head">
                <div className="detail-figs">
                  <span>
                    Spent <b className="num">{money(s.total_out)}</b>
                  </span>
                  <span>
                    Received <b className="num">{money(s.total_in)}</b>
                  </span>
                  <span>
                    Net{" "}
                    <b className="num">
                      {s.net_amount >= 0 ? "+" : "−"}
                      {money(Math.abs(s.net_amount))}
                    </b>
                  </span>
                  <span>
                    Period <b>{periodLabel(s)}</b>
                  </span>
                  <span>
                    <b>{txns.length}</b> transactions
                  </span>
                  <Button
                    variant="ghost"
                    icon={<Icon.ledger size={14} />}
                    onClick={() => setShowRaw((v) => !v)}
                    title="See the raw CSV rows behind this statement"
                  >
                    {showRaw ? "View list" : "View CSV"}
                  </Button>
                </div>
              </div>
            ) : null}

            <div className="stmt-txns-head">
              {showRaw ? "Raw CSV rows" : "Transactions detailed"}
            </div>
            {showRaw ? (
              <RawCsvTable txns={txns} />
            ) : (
              <div className="stmt-txns">
                {txns.map((t) => {
                  const out = Number(t.amount) < 0;
                  const st = status(t);
                  return (
                    <div className="stmt-txn" key={t.id}>
                      <span className="stmt-txn-date">{shortDate(t.txn_date)}</span>
                      <span className="stmt-txn-desc" title={t.description || ""}>
                        {t.description || "—"}
                      </span>
                      <span
                        className="stmt-txn-amt num"
                        style={{ color: out ? "var(--text)" : "var(--good, #3fb27f)" }}
                      >
                        {out ? "−" : "+"}
                        {money(Math.abs(Number(t.amount)))}
                      </span>
                      <span className={`stmt-txn-status ${st.cls}`}>{st.text}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}
