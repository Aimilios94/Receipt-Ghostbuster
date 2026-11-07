// Find any expense, in any month, by vendor or by the name of the photo it was read
// from (e.g. "IMG_0001.jpg"). Opens the same detail popup as the rest of the app.
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api.js";
import { money, paidWithLabel, shortDate } from "../lib/format.js";
import { Icon } from "./icons.jsx";

const norm = (s) =>
  String(s || "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .trim();

export default function ExpenseSearch({ expenses, onOpen }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const { data: photoNames } = useQuery({ queryKey: ["photo-names"], queryFn: api.photoNames });

  const results = useMemo(() => {
    const needle = norm(q);
    if (needle.length < 2) return [];
    return (expenses || [])
      .filter((e) => norm(e.vendor).includes(needle) || norm(photoNames?.[e.id]).includes(needle))
      .sort((a, b) => (b.expense_date || "").localeCompare(a.expense_date || ""));
  }, [q, expenses, photoNames]);

  const shown = results.slice(0, 12);

  return (
    <div className="exp-search" onBlur={(e) => !e.currentTarget.contains(e.relatedTarget) && setOpen(false)}>
      <Icon.search size={14} />
      <input
        className="input exp-search-input"
        type="search"
        placeholder="Search vendor or photo name"
        aria-label="Search expenses by vendor or photo name"
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            setQ("");
            setOpen(false);
          }
        }}
      />
      {open && norm(q).length >= 2 ? (
        <div className="exp-search-results" role="listbox">
          {shown.length ? (
            shown.map((e) => (
              <button
                key={e.id}
                type="button"
                className="exp-search-row"
                onClick={() => {
                  setOpen(false);
                  onOpen(e);
                }}
              >
                <span className="exp-search-vendor">{e.vendor || "Expense"}</span>
                <span className="exp-search-meta">
                  {shortDate(e.expense_date)} {(e.expense_date || "").slice(0, 4)} · {paidWithLabel(e)}
                  {e.status === "pending_review" ? " · in review" : ""}
                  {photoNames?.[e.id] ? ` · ${photoNames[e.id]}` : ""}
                </span>
                <span className="num">{money(e.amount)}</span>
              </button>
            ))
          ) : (
            <div className="exp-search-empty">No expense matches “{q.trim()}”.</div>
          )}
          {results.length > shown.length ? (
            <div className="exp-search-empty">
              Showing {shown.length} of {results.length}. Type more to narrow it down.
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
