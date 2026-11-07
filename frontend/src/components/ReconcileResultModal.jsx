import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Modal, MissingFlag } from "./ui.jsx";
import { Icon } from "./icons.jsx";
import { missingDetails, money, normText, paidWithLabel, shortDate } from "../lib/format.js";
import { api } from "../lib/api.js";
import { useToast } from "./toast.jsx";
import ExpenseEditModal from "./ExpenseEditModal.jsx";
import ReplacePhotoButton from "./ReplacePhotoButton.jsx";
import { ReceiptLightbox } from "./ReceiptLightbox.jsx";
import { useBankMonths } from "../lib/bank.js";

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

// Only SUGGEST a match when there's a real reason, the SAME vendor or an EXACT amount,
// and the dates are at most 3 days apart, the same window the auto-matcher uses. A
// same-vendor line a week away, or a close amount on an unrelated vendor, is NOT
// suggested. The "Others" picker (opt-in) still lets the user force any link by hand.
const SUGGEST_MAX_DAYS = 3;
function plausible(c) {
  return (c.vm || c.ad <= 0.01) && c.dd <= SUGGEST_MAX_DAYS;
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
  const [editing, setEditing] = useState(null);
  const [txnDetail, setTxnDetail] = useState(null);
  const [view, setView] = useState("all");
  const [dismissed, setDismissed] = useState(new Set()); // "expId::txnId" suggestions rejected as "not a match"
  const [history, setHistory] = useState([]); // actions taken in this popup, newest last, for Undo
  const toast = useToast();
  const bankMonths = useBankMonths();

  const record = (entry) =>
    setHistory((h) => [...h, { ...entry, key: Math.random().toString(36).slice(2) }]);

  const dismiss = (expId, txnId) =>
    setDismissed((prev) => new Set(prev).add(`${expId}::${txnId}`));

  const pairs = state.pairs || [];
  const unmatchedExp = state.unmatched_expense_list || [];
  const unmatchedBank = state.unmatched_bank_list || [];

  // Search the lists by vendor, bank description or photo name. Suggestions and
  // Undo still work on the full lists; only what's shown is filtered.
  const [q, setQ] = useState("");
  const { data: photoNames } = useQuery({ queryKey: ["photo-names"], queryFn: api.photoNames });
  const needle = normText(q);
  const hit = (...vals) => !needle || vals.some((v) => normText(v).includes(needle));
  const shownPairs = pairs.filter((p) =>
    hit(p.expense.vendor, p.transaction.description, photoNames?.[p.expense.id])
  );
  const shownExp = unmatchedExp.filter((e) => hit(e.vendor, photoNames?.[e.id]));
  const shownBank = unmatchedBank.filter((t) => hit(t.description));
  const emptyNote = (text) => (needle ? `Nothing here matches “${q.trim()}”.` : text);

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
    const exp = unmatchedExp.find((x) => x.id === expId);
    const txn = unmatchedBank.find((t) => t.id === txnId);
    try {
      apply(await api.matchExpense(expId, txnId));
      if (exp && txn) record({ kind: "match", exp, txn });
      setPickFor(null);
      toast("Matched to the bank transaction");
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusy(null);
    }
  };

  const unmatch = async (pair) => {
    setBusy(pair.expense.id);
    try {
      apply(await api.unmatchExpense(pair.expense.id, pair.transaction.id));
      record({ kind: "unmatch", exp: pair.expense, txn: pair.transaction });
      toast("Unmatched");
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusy(null);
    }
  };

  // Undo the latest action that can still be undone as it was. An Unmatch is only
  // undone while both sides are free, so it can't double-link a bank line the user
  // has since matched to something else; the others check the same way.
  const isMatched = (expId, txnId) => pairs.some((p) => p.expense.id === expId && p.transaction.id === txnId);
  const expOpen = (id) => unmatchedExp.some((e) => e.id === id);
  const txnOpen = (id) => unmatchedBank.some((t) => t.id === id);
  const canUndo = (h) => {
    if (h.kind === "unmatch") return expOpen(h.exp.id) && txnOpen(h.txn.id);
    if (h.kind === "match") return isMatched(h.exp.id, h.txn.id);
    if (h.kind === "noreceipt") return !txnOpen(h.txn.id) && !pairs.some((p) => p.transaction.id === h.txn.id);
    if (h.kind === "dismiss") return dismissed.has(`${h.exp.id}::${h.txn.id}`);
    if (h.kind === "accept") return pairs.some((p) => p.expense.id === h.exp.id && p.accepted);
    return false;
  };
  const last = [...history].reverse().find(canUndo);

  const undoLast = async () => {
    const h = last;
    setBusy("undo");
    try {
      if (h.kind === "unmatch") apply(await api.matchExpense(h.exp.id, h.txn.id));
      else if (h.kind === "match") apply(await api.unmatchExpense(h.exp.id, h.txn.id));
      else if (h.kind === "noreceipt") apply(await api.markNoReceipt(h.txn.id, false));
      else if (h.kind === "accept") apply(await api.acceptDifference(h.exp.id, false));
      else if (h.kind === "dismiss")
        setDismissed((prev) => {
          const next = new Set(prev);
          next.delete(`${h.exp.id}::${h.txn.id}`);
          return next;
        });
      setHistory((list) => list.filter((x) => x.key !== h.key));
      toast("Undone");
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusy(null);
    }
  };

  const amt = (x) => money(Math.abs(Number(x)));
  const describe = (h) => {
    const ev = (
      <>
        <b>{h.exp?.vendor || "Expense"}</b> <span className="num">{amt(h.exp?.amount)}</span>
      </>
    );
    const tv = (
      <>
        <b>{h.txn?.description || "Bank payment"}</b> <span className="num">{amt(h.txn?.amount)}</span>
      </>
    );
    if (h.kind === "unmatch") return <>Unmatched {ev} from {tv}</>;
    if (h.kind === "match") return <>Matched {ev} to {tv}</>;
    if (h.kind === "noreceipt") return <>Marked {tv} as No receipt</>;
    if (h.kind === "accept") return <>Accepted the {money(h.diff)} difference on {ev}</>;
    return <>Hid {tv} as not a match for {ev}</>;
  };

  // Accept the amount difference on a matched pair (e.g. a bank fee), so it stops
  // being an exception. Stored as the exact amount, so a later change shows again.
  const acceptDiff = async (pair) => {
    setBusy(pair.expense.id);
    try {
      apply(await api.acceptDifference(pair.expense.id, true));
      record({ kind: "accept", exp: pair.expense, txn: pair.transaction, diff: pair.amount_diff });
      toast(`Accepted the ${money(pair.amount_diff)} difference`);
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
    const txn = unmatchedBank.find((t) => t.id === txnId);
    try {
      apply(await api.markNoReceipt(txnId, true));
      if (txn) record({ kind: "noreceipt", txn });
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
    { key: "matched", label: "Matched", n: shownPairs.length },
    { key: "unmatched", label: "Unmatched expenses", n: shownExp.length },
    { key: "bank", label: "Bank without receipt", n: shownBank.length },
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
        {last ? (
          <div className="recon-undo" role="status">
            <span className="recon-undo-text">{describe(last)}</span>
            <button className="btn btn-sm" disabled={busy === "undo"} onClick={undoLast}>
              Undo
            </button>
          </div>
        ) : null}

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
          <div className="exp-search recon-search">
            <Icon.search size={14} />
            <input
              className="input exp-search-input"
              type="search"
              placeholder="Search vendor or photo name"
              aria-label="Search these results by vendor, bank description or photo name"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
        </div>

        {/* ---- Matched pairs ---- */}
        {show("matched") ? (
          <>
            <div className="recon-head">Matched · receipt ↔ bank transaction</div>
            {shownPairs.length ? (
              <div className="recon-list">
                {shownPairs.map((p) => (
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
                        <button className="btn btn-sm btn-ghost" onClick={() => setEditing(p.expense)}>
                          <Icon.edit size={13} /> Edit
                        </button>
                        <ReplacePhotoButton
                          expenseId={p.expense.id}
                          onDone={refreshState}
                          hasPhoto={!!p.expense.receipt_image_url}
                        />
                      </div>
                    </div>
                    <div className="recon-arrow">
                      <Icon.reconcile size={16} />
                      {p.amount_diff > 0 ? (
                        p.accepted ? (
                          <span className="recon-diff recon-diff-ok" title="You accepted this difference">
                            Δ {money(p.amount_diff)} accepted
                          </span>
                        ) : (
                          <>
                            <span className="recon-diff">Δ {money(p.amount_diff)}</span>
                            <button
                              className="btn btn-sm btn-ghost"
                              disabled={busy === p.expense.id}
                              title="The amounts differ but it's the same payment, e.g. a bank fee. Stop showing it as an exception."
                              onClick={() => acceptDiff(p)}
                            >
                              Accept difference
                            </button>
                          </>
                        )
                      ) : null}
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
                      onClick={() => unmatch(p)}
                    >
                      Unmatch
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="recon-empty">{emptyNote("Nothing matched automatically.")}</div>
            )}
          </>
        ) : null}

        {/* ---- Unmatched expenses + suggested match ---- */}
        {show("unmatched") ? (
          <>
            <div className="recon-head">
              Card expenses with no bank match <span style={{ color: "var(--text-dim)" }}>· {shownExp.length}</span>
            </div>
            {shownExp.length ? (
              <div className="recon-list">
                {shownExp.map((e) => {
                  const cands = candidatesFor(e);
                  const best = cands.find(plausible); // only a believable suggestion
                  const open = pickFor === e.id;
                  return (
                    <div className="recon-unmatched" key={e.id}>
                      <div className="recon-pair">
                        <div className="recon-side">
                          {cands.length > 0 ? (
                            <button
                              className="recon-vendor recon-vendor-btn"
                              aria-expanded={open}
                              title={`See possible matches (${cands.length})`}
                              onClick={() => setPickFor(open ? null : e.id)}
                            >
                              {e.vendor || "Expense"}
                            </button>
                          ) : (
                            <div className="recon-vendor">{e.vendor || "Expense"}</div>
                          )}
                          <div className="recon-meta">
                            {shortDate(e.expense_date)} · {e.category || "—"} · {paidWithLabel(e)}{" "}
                            <MissingFlag items={missingDetails(e, bankMonths)} />
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
                            <button className="btn btn-sm btn-ghost" onClick={() => setEditing(e)}>
                              <Icon.edit size={13} /> Edit
                            </button>
                            <ReplacePhotoButton
                              expenseId={e.id}
                              onDone={refreshState}
                              hasPhoto={!!e.receipt_image_url}
                            />
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
                                onClick={() => {
                                  dismiss(e.id, best.t.id);
                                  record({ kind: "dismiss", exp: e, txn: best.t });
                                }}
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
                          <div className="recon-meta">Possible matches, closest first. Click one to match it.</div>
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
              <div className="recon-empty">{emptyNote("Every card expense is matched. 🎉")}</div>
            )}
          </>
        ) : null}

        {/* ---- Bank payments still needing a receipt ---- */}
        {show("bank") ? (
          <>
            <div className="recon-head">
              Bank payments still waiting for a receipt{" "}
              <span style={{ color: "var(--text-dim)" }}>· {shownBank.length}</span>
            </div>
            {shownBank.length ? (
              <div className="recon-list">
                {shownBank.map((t) => (
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
              <div className="recon-empty">{emptyNote("No bank payments are waiting for a receipt.")}</div>
            )}
          </>
        ) : null}
      </div>

      {lightbox ? <ReceiptLightbox src={lightbox} onClose={() => setLightbox(null)} /> : null}
      {editing ? (
        <ExpenseEditModal expense={editing} onClose={() => setEditing(null)} onSaved={refreshState} />
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
