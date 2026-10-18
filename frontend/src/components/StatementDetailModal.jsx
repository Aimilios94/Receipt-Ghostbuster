import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api.js";
import { money, shortDate } from "../lib/format.js";
import { Modal, Loading, ErrorBanner } from "./ui.jsx";

function periodLabel(s) {
  return s?.period_start ? `${shortDate(s.period_start)} – ${shortDate(s.period_end)}` : "—";
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
                </div>
              </div>
            ) : null}

            <div className="stmt-txns-head">Transactions detailed</div>
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
          </>
        )}
      </div>
    </Modal>
  );
}
