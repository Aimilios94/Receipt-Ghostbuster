import { useState, useEffect } from "react";

// Tracks which ids the user has already opened, persisted in localStorage so a
// freshly-imported item lights up as "New" until clicked (like a new message).
// On the very first visit everything already present is treated as seen, so only
// genuinely new items highlight afterwards. Used for exceptions and statements.
export function useSeen(key, allIds) {
  const [seen, setSeen] = useState(() => {
    try {
      return new Set(JSON.parse(localStorage.getItem(key) || "[]"));
    } catch {
      return new Set();
    }
  });

  useEffect(() => {
    if (localStorage.getItem(key) === null && allIds && allIds.length) {
      localStorage.setItem(key, JSON.stringify(allIds));
      setSeen(new Set(allIds));
    }
  }, [key, allIds]);

  const mark = (id) => {
    if (!id) return;
    setSeen((prev) => {
      if (prev.has(id)) return prev;
      const next = new Set(prev).add(id);
      localStorage.setItem(key, JSON.stringify([...next]));
      return next;
    });
  };

  const isNew = (id) => !seen.has(id);
  return { isNew, mark };
}
