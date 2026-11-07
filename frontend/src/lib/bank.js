// Which months have an imported bank statement, from each statement's period. A
// card payment in a month with no statement isn't missing anything yet: it's
// waiting for that month's statement.
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api.js";

export function monthsBetween(start, end) {
  const out = [];
  if (!start || !end) return out;
  let [y, m] = String(start).slice(0, 7).split("-").map(Number);
  const [ey, em] = String(end).slice(0, 7).split("-").map(Number);
  while (y < ey || (y === ey && m <= em)) {
    out.push(`${y}-${String(m).padStart(2, "0")}`);
    m += 1;
    if (m > 12) {
      m = 1;
      y += 1;
    }
  }
  return out;
}

// A Set of "YYYY-MM", or null while the statements are loading.
export function useBankMonths() {
  const { data } = useQuery({ queryKey: ["statements"], queryFn: api.listStatements });
  return useMemo(() => {
    if (!data) return null;
    return new Set(data.flatMap((s) => monthsBetween(s.period_start, s.period_end)));
  }, [data]);
}
