import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api.js";
import { money, shortDate } from "../lib/format.js";
import { Modal, Loading, ErrorBanner } from "./ui.jsx";

// Compact group rows. Clicking one opens a small detail popup (not an inline expand),
// so the list stays clean regardless of how many transactions a group has.
function BreakdownList({ rows, nameKey = "vendor", empty, onPick }) {
  if (!rows?.length) {
    return <p style={{ fontSize: 13, color: "var(--text-dim)", margin: "6px 0 0" }}>{empty}</p>;
  }
  return (
    <div className="bd-list">
      {rows.map((r, i) => (
        <button
          type="button"
          className="bd-row"
          key={i}
          onClick={() => r.items?.length && onPick({ title: r[nameKey], items: r.items, total: r.total })}
          title="See the individual transactions"
        >
          <span className="bd-name" title={r[nameKey]}>{r[nameKey]}</span>
          <span className="bd-count">{r.count}×</span>
          <span className="bd-total num">{money(r.total)}</span>
        </button>
      ))}
    </div>
  );
}

// Small popup listing the individual transactions behind one group (date, detail, amount).
function BreakdownDetailModal({ title, items, total, onClose }) {
  return (
    <Modal title={title} onClose={onClose} width={440}>
      <div className="modal-body">
        <div className="bd-detail-list">
          {items.map((it, i) => {
            const label = [it.label, it.category, it.note].filter(Boolean).join(" · ");
            return (
              <div className="bd-detail-item" key={i}>
                <span className="bd-item-date">{shortDate(it.date)}</span>
                <span className="bd-item-label" title={label}>{label || "—"}</span>
                <span className="bd-item-amt num">{money(it.amount)}</span>
              </div>
            );
          })}
        </div>
        <div className="bd-detail-foot">
          <span>{items.length} transaction{items.length === 1 ? "" : "s"}</span>
          <span>Total <b className="num">{money(total)}</b></span>
        </div>
      </div>
    </Modal>
  );
}

// Spending breakdown popup: expenses grouped by vendor (total paid to each) and
// bank transfers split into third parties (sent/received) and own-account movements.
// Opened from both the Reconciliation and the Ledger pages.
export default function BreakdownModal({ onClose }) {
  const [detail, setDetail] = useState(null);
  const { data, isLoading, error } = useQuery({
    queryKey: ["breakdown"],
    queryFn: api.breakdown,
  });
  const vendors = data?.vendors || [];
  const tp = data?.third_parties || { sent: [], received: [], total_sent: 0, total_received: 0 };
  const own = data?.own_movements || { sent: [], received: [], total_sent: 0, total_received: 0 };
  const vendorTotal = vendors.reduce((s, r) => s + Number(r.total || 0), 0);
  const hasOwn = own.sent.length || own.received.length;

  return (
    <Modal title="Spending breakdown" onClose={onClose} width={720}>
      <div className="modal-body">
        <ErrorBanner error={error} />
        {isLoading ? (
          <Loading />
        ) : (
          <>
            <div className="bd-section-head">
              <span>By vendor</span>
              <span className="bd-section-sub">
                {vendors.length} vendor{vendors.length === 1 ? "" : "s"} · total{" "}
                <b className="num">{money(vendorTotal)}</b>
              </span>
            </div>
            <BreakdownList rows={vendors} nameKey="vendor" empty="No expenses yet." onPick={setDetail} />

            <div className="bd-section-head" style={{ marginTop: 22 }}>
              <span>Third parties — money sent</span>
              <span className="bd-section-sub">
                total out <b className="num">{money(tp.total_sent)}</b>
              </span>
            </div>
            <BreakdownList
              rows={tp.sent}
              nameKey="name"
              empty="No transfers sent (no 'Transfer to …' lines in the imported statements)."
              onPick={setDetail}
            />

            <div className="bd-section-head" style={{ marginTop: 22 }}>
              <span>Third parties — money received</span>
              <span className="bd-section-sub">
                total in <b className="num">{money(tp.total_received)}</b>
              </span>
            </div>
            <BreakdownList rows={tp.received} nameKey="name" empty="No transfers received." onPick={setDetail} />

            {hasOwn ? (
              <>
                <div className="bd-section-head" style={{ marginTop: 22 }}>
                  <span>Own account movements (Revolut)</span>
                  <span className="bd-section-sub">
                    out <b className="num">{money(own.total_sent)}</b>
                    {own.total_received ? <> · in <b className="num">{money(own.total_received)}</b></> : null}
                  </span>
                </div>
                <BreakdownList rows={own.sent} nameKey="name" empty="None." onPick={setDetail} />
                {own.received.length ? (
                  <BreakdownList rows={own.received} nameKey="name" empty="" onPick={setDetail} />
                ) : null}
              </>
            ) : null}

            <p style={{ fontSize: 11.5, color: "var(--text-dim)", margin: "20px 0 0", lineHeight: 1.5 }}>
              Click any row to see its individual transactions. Vendors are your ledger expenses grouped by
              merchant; third parties are person-to-person transfers; own account movements are transfers
              to/from your own Revolut (savings, fees), shown separately.
            </p>
          </>
        )}
      </div>

      {detail ? <BreakdownDetailModal {...detail} onClose={() => setDetail(null)} /> : null}
    </Modal>
  );
}
