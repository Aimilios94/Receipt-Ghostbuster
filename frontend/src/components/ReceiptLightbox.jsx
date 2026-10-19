import { useEffect } from "react";
import { Icon } from "./icons.jsx";

// A fullscreen receipt-image viewer that layers above whatever modal opened it.
// Esc — and the X button or a backdrop click — close ONLY the lightbox: a
// capture-phase key handler runs before any parent Modal's Esc→onClose, so the
// underlying dialog (duplicate compare, expense detail, reconcile results, …)
// stays open and the user keeps their place. Render it conditionally:
//   {src ? <ReceiptLightbox src={src} onClose={() => setSrc(null)} /> : null}
export function ReceiptLightbox({ src, onClose }) {
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") {
        e.stopImmediatePropagation();
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  return (
    <div className="overlay receipt-lightbox" onMouseDown={onClose}>
      <button
        type="button"
        className="lightbox-close"
        aria-label="Close receipt"
        onMouseDown={(e) => {
          e.stopPropagation();
          onClose();
        }}
      >
        <Icon.x size={18} />
      </button>
      <img src={src} alt="Receipt" onMouseDown={(e) => e.stopPropagation()} />
    </div>
  );
}

export default ReceiptLightbox;
