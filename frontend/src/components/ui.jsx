// Small presentational primitives used across pages.
import { useEffect } from "react";
import { createPortal } from "react-dom";
import { Icon } from "./icons.jsx";

export function Card({ className = "", children, style, onClick, title }) {
  const clickable = typeof onClick === "function";
  const a11y = clickable
    ? {
        role: "button",
        tabIndex: 0,
        title,
        onKeyDown: (e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onClick(e);
          }
        },
      }
    : {};
  return (
    <div
      className={`card ${className}${clickable ? " card-click" : ""}`}
      style={style}
      onClick={onClick}
      {...a11y}
    >
      {children}
    </div>
  );
}

export function Button({ variant = "", size = "", icon, children, ...rest }) {
  const cls = ["btn", variant && `btn-${variant}`, size && `btn-${size}`]
    .filter(Boolean)
    .join(" ");
  return (
    <button className={cls} {...rest}>
      {icon ? <span className="ico">{icon}</span> : null}
      {children}
    </button>
  );
}

export function Badge({ tone = "muted", icon, children }) {
  return (
    <span className={`badge badge-${tone}`}>
      {icon ? <span className="bico">{icon}</span> : null}
      {children}
    </span>
  );
}

// Maps an expense row to its ledger status chip.
export function StatusBadge({ expense }) {
  const { status, reconciled, source, vat_amount, matched_transaction_id } = expense;
  if (status === "pending_review")
    return <Badge tone="amber" icon={<Icon.warn size={12} />}>Needs review</Badge>;
  if (source === "cash")
    return <Badge tone="muted" icon={<Icon.receipt size={12} />}>Cash, not matched</Badge>;
  if (reconciled || matched_transaction_id)
    return <Badge tone="green" icon={<Icon.check size={12} />}>Reconciled</Badge>;
  if (vat_amount == null)
    return <Badge tone="amber" icon={<Icon.warn size={12} />}>VAT missing</Badge>;
  return <Badge tone="muted">Unmatched</Badge>;
}

export function Modal({ title, onClose, children, footer, width }) {
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Rendered through a portal to <body> so the fixed overlay always anchors to the
  // viewport — page containers (e.g. `.rise`) carry a transform, which would otherwise
  // make `position: fixed` relative to them and push the modal off-screen.
  return createPortal(
    <div className="overlay" onMouseDown={onClose}>
      <div
        className="modal"
        style={width ? { maxWidth: width } : undefined}
        onMouseDown={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="x-btn" onClick={onClose} aria-label="Close">
            <Icon.x size={17} />
          </button>
        </div>
        {children}
        {footer ? <div className="modal-foot">{footer}</div> : null}
      </div>
    </div>,
    document.body
  );
}

export function Loading({ label = "Loading…" }) {
  return (
    <div className="loading">
      <div className="spinner" />
      {label}
    </div>
  );
}

export function ErrorBanner({ error }) {
  if (!error) return null;
  return <div className="error-banner">{error.message || String(error)}</div>;
}

export function Empty({ icon, children }) {
  return (
    <div className="empty">
      {icon ? <span className="ico">{icon}</span> : null}
      {children}
    </div>
  );
}
