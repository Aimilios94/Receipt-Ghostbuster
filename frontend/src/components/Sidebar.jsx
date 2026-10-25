import { NavLink } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Icon } from "./icons.jsx";
import { api } from "../lib/api.js";

const NAV = [
  { to: "/", label: "Dashboard", icon: Icon.dashboard, end: true },
  { to: "/review", label: "Review queue", icon: Icon.review, badge: "review" },
  { to: "/reconciliation", label: "Reconciliation", icon: Icon.reconcile, badge: "exc" },
  { to: "/bank-statements", label: "Bank statements", icon: Icon.bank, badge: "statements" },
  { to: "/close", label: "Monthly close", icon: Icon.close },
  { to: "/ledger", label: "Ledger", icon: Icon.ledger },
  { to: "/refunds", label: "Refund Hunter", icon: Icon.refund, badge: "flagged" },
  { to: "/advice", label: "Advice", icon: Icon.advice },
  { to: "/model-evals", label: "Model & Evals", icon: Icon.gauge },
];

export default function Sidebar() {
  // Live badge counts — cheap, cached, shared with the pages.
  const { data: review } = useQuery({
    queryKey: ["review-queue"],
    queryFn: api.reviewQueue,
  });
  const { data: exc } = useQuery({ queryKey: ["exceptions"], queryFn: () => api.exceptions() });
  const { data: subs } = useQuery({ queryKey: ["subscriptions"], queryFn: api.listSubscriptions });
  const { data: statements } = useQuery({ queryKey: ["statements"], queryFn: api.listStatements });

  const reviewCount = review?.length || 0;
  // Unmatched bank payments are surfaced per-statement (Bank statements), not here,
  // so exclude them from the Reconciliation badge.
  const excCount = exc
    ? Object.entries(exc.counts || {})
        .filter(([k]) => k !== "unmatched_bank")
        .reduce((a, [, v]) => a + v, 0)
    : 0;
  const flaggedCount = (subs || []).filter(
    (s) => s.status === "flagged" || (s.status === "active" && s.stale)
  ).length;
  const statementsNeeding = (statements || []).filter((s) => s.needs_receipt_count > 0).length;

  const badgeFor = (kind) => {
    if (kind === "review" && reviewCount)
      return <span className="nav-count">{reviewCount}</span>;
    if (kind === "exc" && excCount)
      return <span className="nav-count amber">{excCount}</span>;
    if (kind === "statements" && statementsNeeding)
      return <span className="nav-count amber">{statementsNeeding}</span>;
    if (kind === "flagged" && flaggedCount)
      return <span className="nav-count amber">{flaggedCount}</span>;
    return null;
  };

  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="#fff">
            <path d="M12 3a7 7 0 0 0-7 7v9l2-1.6L9 19l2-1.6L13 19l2-1.6L17 19l2-1.6V10a7 7 0 0 0-7-7z" />
            <circle cx="9.5" cy="10.5" r="1.3" fill="#6a58f0" />
            <circle cx="14.5" cy="10.5" r="1.3" fill="#6a58f0" />
          </svg>
        </span>
        <span className="brand-name">Receipt Ghostbuster</span>
      </div>

      <nav className="nav-group">
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
          >
            <span className="nav-ico">
              <n.icon size={17} />
            </span>
            {n.label}
            {badgeFor(n.badge)}
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-foot">
        <span className="avatar">A</span>
        <div className="meta">
          <b>Personal account</b>
          <br />
          <span>EUR · card ending 4821</span>
        </div>
      </div>
    </aside>
  );
}
