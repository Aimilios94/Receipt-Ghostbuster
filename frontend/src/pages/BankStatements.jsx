import { useState, useMemo, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api.js";
import { money, shortDate } from "../lib/format.js";
import { Card, Button, Loading, ErrorBanner, Empty } from "../components/ui.jsx";
import { Icon } from "../components/icons.jsx";
import ImportBankModal from "../components/ImportBankModal.jsx";
import StatementDetailModal from "../components/StatementDetailModal.jsx";
import { useToast } from "../components/toast.jsx";
import { useSeen } from "../lib/useSeen.js";

const SEEN_KEY = "rg_seen_statements";

function period(s) {
  return s.period_start ? `${shortDate(s.period_start)} – ${shortDate(s.period_end)}` : "—";
}

export default function BankStatements() {
  const qc = useQueryClient();
  const toast = useToast();
  const [showImport, setShowImport] = useState(false);
  const [openId, setOpenId] = useState(null);
  const [params, setParams] = useSearchParams();

  const { data: statements, isLoading, error } = useQuery({
    queryKey: ["statements"],
    queryFn: api.listStatements,
  });

  const ids = useMemo(() => (statements || []).map((s) => s.id), [statements]);
  const { isNew, mark } = useSeen(SEEN_KEY, ids);

  const openStatement = (s) => {
    setOpenId(s.id);
    mark(s.id);
  };

  // Deep-link from the dashboard / reconciliation: /bank-statements?open=<id>.
  useEffect(() => {
    const target = params.get("open");
    if (target && statements?.some((s) => s.id === target)) {
      setOpenId(target);
      mark(target);
      params.delete("open");
      setParams(params, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params, statements]);

  const remove = async (s) => {
    if (!window.confirm(`Delete "${s.filename}" and its ${s.txn_count} transactions? This can't be undone.`))
      return;
    try {
      await api.deleteStatement(s.id);
      ["statements", "exceptions", "close", "expenses", "subscriptions"].forEach((k) =>
        qc.invalidateQueries({ queryKey: [k] })
      );
      toast("Statement deleted");
    } catch (e) {
      toast(e.message, "err");
    }
  };

  const rows = statements || [];

  return (
    <div className="rise">
      <div className="page-head">
        <div>
          <h1 className="page-title">Bank statements</h1>
          <div className="page-sub">
            Every bank statement you've imported — the period it covers and its totals. Click one to
            see its transactions and which payments still need a receipt.
          </div>
        </div>
        <div className="head-actions">
          <Button variant="primary" icon={<Icon.upload size={15} />} onClick={() => setShowImport(true)}>
            Import bank statement
          </Button>
        </div>
      </div>

      <ErrorBanner error={error} />

      {isLoading ? (
        <Loading />
      ) : rows.length === 0 ? (
        <Card className="card-pad">
          <Empty icon={<Icon.bank size={30} />}>
            No statements imported yet. Import a CSV or PDF to start reconciling.
          </Empty>
        </Card>
      ) : (
        <Card className="card-pad">
          <div className="table-wrap">
            <table className="ledger">
              <thead>
                <tr>
                  <th>File</th>
                  <th>Uploaded</th>
                  <th>Period</th>
                  <th className="num-col">Txns</th>
                  <th className="num-col">Spent</th>
                  <th className="num-col">Received</th>
                  <th className="num-col">Net</th>
                  <th>Needs receipt</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => (
                  <tr key={s.id} className="row-click" onClick={() => openStatement(s)}>
                    <td>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                        <Icon.bank size={15} />
                        <b>{s.filename || "statement"}</b>
                        <span className="badge">{(s.source_type || "csv").toUpperCase()}</span>
                        {isNew(s.id) ? <span className="exc-new-tag">New</span> : null}
                      </span>
                    </td>
                    <td>{shortDate(s.uploaded_at)}</td>
                    <td>{period(s)}</td>
                    <td className="num-col num">{s.txn_count}</td>
                    <td className="num-col num">{money(s.total_out)}</td>
                    <td className="num-col num">{money(s.total_in)}</td>
                    <td className="num-col num">
                      {s.net_amount >= 0 ? "+" : "−"}
                      {money(Math.abs(s.net_amount))}
                    </td>
                    <td>
                      {s.needs_receipt_count ? (
                        <span className="tag-open">{s.needs_receipt_count}</span>
                      ) : (
                        <span style={{ color: "var(--text-dim)" }}>All matched</span>
                      )}
                    </td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <button
                        type="button"
                        className="x-btn"
                        title="Delete this statement"
                        aria-label="Delete this statement"
                        onClick={() => remove(s)}
                      >
                        <Icon.x size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {showImport && <ImportBankModal onClose={() => setShowImport(false)} />}
      {openId && <StatementDetailModal id={openId} onClose={() => setOpenId(null)} />}
    </div>
  );
}
