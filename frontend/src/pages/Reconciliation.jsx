import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api.js";
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

export default function Reconciliation() {
  const qc = useQueryClient();
  const toast = useToast();
  const [running, setRunning] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const { data, isLoading, error } = useQuery({ queryKey: ["exceptions"], queryFn: api.exceptions });

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
            Match card expenses to your imported bank statement. Cash is excluded by design.
          </div>
        </div>
        <div className="head-actions">
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
