import { useState } from "react";
import { Modal } from "./ui.jsx";
import { Icon } from "./icons.jsx";
import { money, shortDate } from "../lib/format.js";
import { api } from "../lib/api.js";
import { useToast } from "./toast.jsx";
import EditReceiptButton from "./EditReceiptButton.jsx";

function dayDiff(a, b) {
  const da = Date.parse(a), db = Date.parse(b);
  if (Number.isNaN(da) || Number.isNaN(db)) return 999;
  return Math.round(Math.abs(da - db) / 86400000);
}

// Loose vendor/description similarity so "Uber Eats" ↔ "Uber Eats" (even with a
// discount-driven amount gap) ranks ahead of an unrelated same-amount line.
// Generic tokens (domain suffixes, company forms) don't count as a vendor match.
const _VENDOR_STOPWORDS = new Set([
  "com", "www", "pt", "lda", "ltd", "sa", "inc", "the", "de", "do", "da", "net", "org", "eu",
]);
function vendorMatch(a, b) {
  const norm = (s) => (s || "").toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
  a = norm(a);
  b = norm(b);
  if (!a || !b) return false;
  const tok = (s) => s.split(" ").filter((w) => w.length > 2 && !_VENDOR_STOPWORDS.has(w));
  const ta = new Set(tok(a));
  if ([...ta].some((w) => b.includes(w))) return true; // a meaningful token of a appears in b
  return tok(b).some((w) => ta.has(w));
}

// Only SUGGEST a match when there's a real reason: the SAME vendor, or an EXACT
// amount within a few days (e.g. a payment gateway vs the merchant name). A merely
// close amount on an unrelated vendor is NOT suggested — no random pairings. The
// "Others" picker (opt-in) still lets the user force any link by hand.
function plausible(c) {
  return c.vm || (c.ad <= 0.01 && c.dd <= 7);
}

function fitNote(c) {
  const bits = [];
  if (c.vm) bits.push("same vendor");
  bits.push(c.ad === 0 ? "same amount" : `Δ${money(c.ad)}`);
  if (c.dd > 3) bits.push(`${c.dd}d apart`);
  return bits.join(" · ");
}

// Results of a reconciliation run. The summary figures double as filters; the
// unmatched expenses are shown next to their closest bank candidate with a central
// Match button (for likely pairs that differ only by date); both receipts and bank
// transactions can be inspected.
export default function ReconcileResultModal({ initialState, onClose, onChanged }) {
  const [state, setState] = useState(initialState);
  const [busy, setBusy] = useState(null);
  const [pickFor, setPickFor] = useState(null);
  const [lightbox, setLightbox] = useState(null);
  const [txnDetail, setTxnDetail] = useState(null);
  const [view, setView] = useState("all");
  const [dismissed, setDismissed] = useState(new Set()); // "expId::txnId" suggestions rejected as "not a match"
  const toast = useToast();

  const dismiss = (expId, txnId) =>
    setDismissed((prev) => new Set(prev).add(`${expId}::${txnId}`));

  const pairs = state.pairs || [];
  const unmatchedExp = state.unmatched_expense_list || [];
  const unmatchedBank = state.unmatched_bank_list || [];

  const apply = (next) => {
    setState(next);
    onChanged?.();
  };

  // Re-read current state after an out-of-band change (e.g. a receipt re-scan).
  const refreshState = async () => {
    try {
      apply(await api.reconcileState());
    } catch {
      /* best-effort */
    }
  };

  const match = async (expId, txnId) => {
    setBusy(expId);
    try {
      apply(await api.matchExpense(expId, txnId));
      setPickFor(null);
      toast("Matched to the bank transaction");
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusy(null);
    }
  };

  const unmatch = async (expId, txnId) => {
    setBusy(expId);
    try {
      apply(await api.unmatchExpense(expId, txnId));
      toast("Unmatched");
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusy(null);
    }
  };

  // Acknowledge a bank payment that will never have a receipt (an online payment) —
  // it leaves the reconciliation cycle.
  const markNoReceipt = async (txnId) => {
    setBusy(txnId);
    try {
      apply(await api.markNoReceipt(txnId, true));
      toast("Marked as an online payment (no receipt)");
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusy(null);
    }
  };

  // Unmatched bank candidates for an expense, closest amount then date first.
  // Candidates the user marked "not a match" are hidden.
  const candidatesFor = (exp) => {
    const ea = Math.abs(Number(exp.amount));
    return unmatchedBank
      .filter((t) => !dismissed.has(`${exp.id}::${t.id}`))
      .map((t) => ({
        t,
        ad: Math.abs(Math.abs(Number(t.amount)) - ea),
        dd: dayDiff(t.txn_date, exp.expense_date),
        vm: vendorMatch(exp.vendor, t.description),
      }))
      // vendor match first, then closest amount, then closest date.
      .sort((a, b) => b.vm - a.vm || a.ad - b.ad || a.dd - b.dd);
  };

  const tabs = [
    { key: "all", label: "All" },
    { key: "matched", label: "Matched", n: pairs.length },
    { key: "unmatched", label: "Unmatched expenses", n: unmatchedExp.length },
    { key: "bank", label: "Bank without receipt", n: unmatchedBank.length },
  ];
  const show = (k) => view === "all" || view === k;

  const ViewTxnBtn = ({ t }) => (
    <button className="btn btn-sm btn-ghost" onClick={() => setTxnDetail(t)}>
      <Icon.search size={13} /> View transaction
    </button>
  );

  return (
    <Modal title="Reconciliation results" onClose={onClose} width={920}>
      <div className="modal-body">
        {/* Summary figures double as filters. */}
        <div className="recon-tabs">
          {tabs.map((t) => (
            <button
              key={t.key}
              className={`recon-tab${view === t.key ? " active" : ""}`}
              onClick={() => setView(t.key)}
            >
              {t.label}
              {t.n != null ? <b className="num"> {t.n}</b> : null}
            </button>
          ))}
        </div>

        {/* ---- Matched pairs ---- */}
        {show("matched") ? (
          <>
            <div className="recon-head">Matched · receipt ↔ bank transaction</div>
            {pairs.length ? (
              <div className="recon-list">
                {pairs.map((p) => (
                  <div className="recon-pair" key={p.expense.id}>
                    <div className="recon-side">
                      <div className="recon-vendor">{p.expense.vendor || "Expense"}</div>
                      <div className="recon-meta">
                        {shortDate(p.expense.expense_date)} · {p.expense.category || "—"}
                      </div>
                      <div className="recon-amt num">{money(p.expense.amount)}</div>
                      <div className="recon-receipt-actions">
                        {p.expense.receipt_image_url ? (
                          <button className="btn btn-sm btn-ghost" onClick={() => setLightbox(p.expense.receipt_image_url)}>
                            <Icon.receipt size={13} /> View receipt
                          </button>
                        ) : (
                          <span className="recon-noreceipt">No receipt image</span>
                        )}
                        <EditReceiptButton expenseId={p.expense.id} onDone={refreshState} />
                      </div>
                    </div>
                    <div className="recon-arrow">
                      <Icon.reconcile size={16} />
                      {p.amount_diff > 0 ? <span className="recon-diff">Δ {money(p.amount_diff)}</span> : null}
                    </div>
                    <div className="recon-side recon-side-bank">
                      <div className="recon-vendor">{p.transaction.description || "Bank payment"}</div>
                      <div className="recon-meta">{shortDate(p.transaction.txn_date)} · from the statement</div>
                      <div className="recon-amt num">{money(Math.abs(Number(p.transaction.amount)))}</div>
                      <ViewTxnBtn t={p.transaction} />
                    </div>
                    <button
                      className="btn btn-sm"
                      disabled={busy === p.expense.id}
                      onClick={() => unmatch(p.expense.id, p.transaction.id)}
                    >
                      Unmatch
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="recon-empty">Nothing matched automatically.</div>
            )}
          </>
        ) : null}

        {/* ---- Unmatched expenses + suggested match ---- */}
        {show("unmatched") ? (
          <>
            <div className="recon-head">
              Card expenses with no bank match <span style={{ color: "var(--text-dim)" }}>· {unmatchedExp.length}</span>
            </div>
            {unmatchedExp.length ? (
              <div className="recon-list">
                {unmatchedExp.map((e) => {
                  const cands = candidatesFor(e);
                  const best = cands.find(plausible); // only a believable suggestion
                  const open = pickFor === e.id;
                  return (
                    <div className="recon-unmatched" key={e.id}>
                      <div className="recon-pair">
                        <div className="recon-side">
                          <div className="recon-vendor">{e.vendor || "Expense"}</div>
                          <div className="recon-meta">
                            {shortDate(e.expense_date)} · {e.category || "—"} · {e.source}
                          </div>
                          <div className="recon-amt num">{money(e.amount)}</div>
                          <div className="recon-receipt-actions">
                            {e.receipt_image_url ? (
                              <button className="btn btn-sm btn-ghost" onClick={() => setLightbox(e.receipt_image_url)}>
                                <Icon.receipt size={13} /> View receipt
                              </button>
                            ) : (
                              <span className="recon-noreceipt">No receipt image</span>
                            )}
                            <EditReceiptButton expenseId={e.id} onDone={refreshState} />
                          </div>
                        </div>
                        <div className="recon-arrow">
                          {best ? (
                            <>
                              <button
                                className="btn btn-sm btn-primary"
                                disabled={busy === e.id}
                                onClick={() => match(e.id, best.t.id)}
                                title="Match this receipt to the bank transaction"
                              >
                                Match →
                              </button>
                              <button
                                className="btn btn-sm btn-ghost"
                                onClick={() => dismiss(e.id, best.t.id)}
                                title="Not the same payment — keep this expense unmatched"
                              >
                                Not a match
                              </button>
                              <span className="recon-diff">{fitNote(best)}</span>
                            </>
                          ) : (
                            <span className="recon-noreceipt">No likely match</span>
                          )}
                        </div>
                        <div className="recon-side recon-side-bank">
                          {best ? (
                            <>
                              <div className="recon-vendor">{best.t.description || "Bank payment"}</div>
                              <div className="recon-meta">{shortDate(best.t.txn_date)} · likely match</div>
                              <div className="recon-amt num">{money(Math.abs(Number(best.t.amount)))}</div>
                              <ViewTxnBtn t={best.t} />
                            </>
                          ) : (
                            <span className="recon-meta">Stays pending — pick one under “Others” if you know it</span>
                          )}
                        </div>
                        {cands.length > 0 ? (
                          <button className="btn btn-sm" onClick={() => setPickFor(open ? null : e.id)}>
                            {open ? "Hide" : "Others"}
                          </button>
                        ) : (
                          <span />
                        )}
                      </div>
                      {open ? (
                        <div className="recon-cands">
                          {cands.slice(0, 10).map((c) => (
                            <button
                              key={c.t.id}
                              className="recon-cand"
                              disabled={busy === e.id}
                              onClick={() => match(e.id, c.t.id)}
                            >
                              <span className="recon-cand-desc">{c.t.description || "Bank payment"}</span>
                              <span className="recon-meta">{shortDate(c.t.txn_date)}</span>
                              <span className="num">{money(Math.abs(Number(c.t.amount)))}</span>
                              <span className="recon-cand-fit">{fitNote(c)}</span>
                            </button>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="recon-empty">Every card expense is matched. 🎉</div>
            )}
          </>
        ) : null}

        {/* ---- Bank payments still needing a receipt ---- */}
        {show("bank") ? (
          <>
            <div className="recon-head">
              Bank payments still waiting for a receipt{" "}
              <span style={{ color: "var(--text-dim)" }}>· {unmatchedBank.length}</span>
            </div>
            {unmatchedBank.length ? (
              <div className="recon-list">
                {unmatchedBank.map((t) => (
                  <div className="recon-bankrow" key={t.id}>
                    <span className="recon-vendor">{t.description || "Bank payment"}</span>
                    <span className="recon-meta">{shortDate(t.txn_date)}</span>
                    <span className="recon-amt num">{money(Math.abs(Number(t.amount)))}</span>
                    <ViewTxnBtn t={t} />
                    <button
                      className="btn btn-sm"
                      disabled={busy === t.id}
                      title="This is an online payment with no receipt — take it out of reconciliation"
                      onClick={() => markNoReceipt(t.id)}
                    >
                      No receipt
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="recon-empty">No bank payments are waiting for a receipt.</div>
            )}
          </>
        ) : null}
      </div>

      {lightbox ? (
        <div className="overlay receipt-lightbox" onMouseDown={() => setLightbox(null)}>
          <img src={lightbox} alt="Receipt" onMouseDown={(ev) => ev.stopPropagation()} />
        </div>
      ) : null}

      {txnDetail ? <BankTxnDetail txn={txnDetail} onClose={() => setTxnDetail(null)} /> : null}
    </Modal>
  );
}

// "View" for a bank transaction — the counterpart of viewing a receipt. Shows the
// exact row as it came from the statement file (its CSV columns).
function BankTxnDetail({ txn, onClose }) {
  const raw = txn.raw && typeof txn.raw === "object" ? txn.raw : null;
  return (
    <div className="overlay" onMouseDown={onClose}>
      <div className="bank-detail" onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>Bank transaction</h3>
          <button className="x-btn" onClick={onClose} aria-label="Close">
            <Icon.x size={17} />
          </button>
        </div>
        <div className="bank-detail-body">
          <div className="detail-figs">
            <span>
              Date <b>{shortDate(txn.txn_date)}</b>
            </span>
            <span>
              Amount{" "}
              <b className="num">
                {Number(txn.amount) < 0 ? "−" : "+"}
                {money(Math.abs(Number(txn.amount)))}
              </b>
            </span>
            {txn.balance != null ? (
              <span>
                Balance <b className="num">{money(txn.balance)}</b>
              </span>
            ) : null}
          </div>
          <div className="bank-detail-desc">{txn.description || "—"}</div>
          {txn.source_file ? (
            <div className="recon-meta">From {txn.source_file}</div>
          ) : null}
          {raw ? (
            <>
              <div className="recon-head" style={{ marginTop: 4 }}>From the statement file</div>
              <table className="bank-raw">
                <tbody>
                  {Object.entries(raw).map(([k, v]) => (
                    <tr key={k}>
                      <td>{k}</td>
                      <td>{String(v)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
