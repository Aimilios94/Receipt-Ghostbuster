// Formatting + small domain helpers shared across the app.

const EUR = new Intl.NumberFormat("en-IE", {
  style: "currency",
  currency: "EUR",
  minimumFractionDigits: 2,
});

export function money(value, { currency = "EUR" } = {}) {
  const n = Number(value ?? 0);
  if (currency === "EUR") return EUR.format(n);
  return new Intl.NumberFormat("en-IE", { style: "currency", currency }).format(n);
}

// "2026-09-28" -> "28 Sep"
export function shortDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso + (iso.length === 10 ? "T00:00:00" : ""));
  if (isNaN(d)) return iso;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

// "2026-09" -> "September 2026"
export function monthLabel(ym) {
  if (!ym) return "";
  const [y, m] = ym.split("-").map(Number);
  const d = new Date(y, m - 1, 1);
  return d.toLocaleDateString("en-GB", { month: "long", year: "numeric" });
}

export function currentMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

// The most recent YYYY-MM present in a list of expenses. Lets the app open
// on the month that actually has data instead of an empty current month.
export function latestMonth(expenses) {
  const months = (expenses || []).map((e) => (e.expense_date || "").slice(0, 7)).filter(Boolean);
  if (!months.length) return null;
  return months.sort().at(-1);
}

export function pct(part, whole) {
  if (!whole) return 0;
  return Math.round((part / whole) * 100);
}

// Human label for a source value
export function sourceLabel(src) {
  return { card: "Card", cash: "Cash", bank: "Bank" }[src] || src || "—";
}

// Confidence as a percentage integer
export function confPct(c) {
  if (c == null) return null;
  return Math.round(c * 100);
}

export const CATEGORY_COLORS = [
  "var(--cat-1)",
  "var(--cat-2)",
  "var(--cat-3)",
  "var(--cat-4)",
  "var(--cat-5)",
  "var(--cat-6)",
  "var(--cat-7)",
];
