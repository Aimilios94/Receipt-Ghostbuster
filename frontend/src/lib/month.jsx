// The one month Dashboard, Reconciliation, Monthly close and Advice all show. It moves
// only when the user picks another one, never because a receipt was uploaded.
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api.js";
import { currentMonth, latestMonth, money, monthLabel } from "./format.js";
import { useToast } from "../components/toast.jsx";

const STORAGE_KEY = "rg_month";
const MONTH_PAGES = new Set(["/", "/reconciliation", "/close", "/advice"]);
const LONG_TOAST_MS = 9000;

const MonthCtx = createContext(null);

function readChosen() {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return /^\d{4}-\d{2}$/.test(value || "") ? value : null;
  } catch {
    return null;
  }
}

export function MonthProvider({ children }) {
  const { data: expenses, isSuccess } = useQuery({
    queryKey: ["expenses"],
    queryFn: () => api.listExpenses(),
  });
  const [chosen, setChosen] = useState(readChosen);
  // With no choice yet, the newest month with data at the moment the app opens. It's
  // set once, so a later upload for a newer month doesn't move the screen.
  const [opened, setOpened] = useState(null);

  useEffect(() => {
    if (!opened && isSuccess) setOpened(latestMonth(expenses) || currentMonth());
  }, [opened, isSuccess, expenses]);

  const setMonth = useCallback((value) => {
    setChosen(value);
    try {
      localStorage.setItem(STORAGE_KEY, value);
    } catch {
      /* the choice still holds until the page reloads */
    }
  }, []);

  const value = useMemo(
    () => ({ month: chosen || opened || currentMonth(), setMonth, expenses }),
    [chosen, opened, setMonth, expenses]
  );
  return <MonthCtx.Provider value={value}>{children}</MonthCtx.Provider>;
}

export function useMonth() {
  return useContext(MonthCtx);
}

function recentMonths(n = 6) {
  const out = [];
  const d = new Date();
  for (let i = 0; i < n; i++) {
    const m = new Date(d.getFullYear(), d.getMonth() - i, 1);
    out.push(`${m.getFullYear()}-${String(m.getMonth() + 1).padStart(2, "0")}`);
  }
  return out;
}

export function MonthPicker({ width = 170 }) {
  const { month, setMonth, expenses } = useMonth();
  const options = useMemo(() => {
    const fromData = (expenses || []).map((e) => (e.expense_date || "").slice(0, 7)).filter(Boolean);
    return [...new Set([month, ...recentMonths(), ...fromData])].sort().reverse();
  }, [month, expenses]);

  return (
    <select
      className="select"
      style={{ width }}
      aria-label="Month"
      value={month}
      onChange={(e) => setMonth(e.target.value)}
    >
      {options.map((m) => (
        <option key={m} value={m}>
          {monthLabel(m)}
        </option>
      ))}
    </select>
  );
}

// "2026-10" next to "2026-11" -> "October"; across a year -> "October 2025".
function monthName(ym, other) {
  const label = monthLabel(ym);
  return ym.slice(0, 4) === other.slice(0, 4) ? label.split(" ")[0] : label;
}

// Toast for a saved expense. If it landed in a month other than the one on screen, the
// toast says so, stays longer and offers a button to go there.
export function useExpenseToast() {
  const toast = useToast();
  const { month, setMonth } = useMonth();
  const navigate = useNavigate();
  const { pathname } = useLocation();

  return (expense, message, verb = "Posted", extraActions = []) => {
    const target = (expense?.expense_date || "").slice(0, 7);
    if (!target || target === month || expense?.status === "pending_review") {
      toast(message, "ok", extraActions.length ? { duration: LONG_TOAST_MS, actions: extraActions } : {});
      return;
    }
    const onMonthPage = MONTH_PAGES.has(pathname);
    const viewing = monthName(month, target);
    toast(
      `${verb} ${expense.vendor || "expense"} ${money(expense.amount)} to ${monthLabel(target)}. ` +
        (onMonthPage ? `You're viewing ${viewing}.` : `Your dashboard is on ${viewing}.`),
      "ok",
      {
        duration: LONG_TOAST_MS,
        actions: extraActions,
        action: {
          label: `View ${monthName(target, month)}`,
          onClick: () => {
            setMonth(target);
            if (!onMonthPage) navigate("/");
          },
        },
      }
    );
  };
}
