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

// VAT summed PER RATE across a set of expenses — mirrors the backend engine.
// For each receipt with line items we compute its OWN per-rate VAT bucket-first
// (gross per rate -> VAT once), matching its printed summary, then add those
// bucket VATs into the rate totals; an expense with no line items falls back to
// its single stored rate. `lineItemsByExpense` is a Map(expense_id -> [lines]).
// Returns [{ rate, vat, label }] sorted by VAT desc; rate null -> "Unknown rate".
export function vatByRate(expenses, lineItemsByExpense) {
  const buckets = new Map(); // rate(number|null) -> vat total
  const add = (rate, vat) => {
    const key = rate == null ? null : Number(rate);
    buckets.set(key, (buckets.get(key) || 0) + Number(vat || 0));
  };
  for (const e of expenses || []) {
    const lines = lineItemsByExpense?.get(e.id);
    if (lines && lines.length) {
      // This receipt's own bucket-first breakdown.
      const grossByRate = new Map();
      for (const li of lines) {
        if (li.amount == null) continue;
        const key = li.vat_rate == null ? null : Number(li.vat_rate);
        grossByRate.set(key, (grossByRate.get(key) || 0) + Number(li.amount || 0));
      }
      for (const [rate, gross] of grossByRate) add(rate, lineVat(gross, rate || 0));
    } else if (e.vat_amount) {
      add(e.vat_rate, e.vat_amount);
    }
  }
  return [...buckets.entries()]
    .map(([rate, vat]) => ({
      rate,
      vat: Math.round(vat * 100) / 100,
      label: rate == null ? "Unknown rate" : `${rate}%`,
    }))
    .filter((r) => r.vat !== 0)
    .sort((a, b) => b.vat - a.vat);
}

// VAT portion of one gross line at its rate — mirrors the backend split_gross.
export function lineVat(amount, rate) {
  const g = Number(amount || 0);
  const r = Number(rate || 0);
  if (!g || !r) return 0;
  const net = g / (1 + r / 100);
  return Math.round((g - net) * 100) / 100;
}

// Group editable VAT lines by rate for a live preview. VAT is computed on each
// rate's gross TOTAL (bucket-first), matching the backend + the printed receipt
// summary — not summed per-line. Returns [{ rate, vat, base, label }].
export function vatByRateLines(lines) {
  const grossByRate = new Map(); // rate -> summed gross
  for (const li of lines || []) {
    const amt = Number(li.amount || 0);
    if (!amt) continue;
    const key = li.vat_rate === "" || li.vat_rate == null ? 0 : Number(li.vat_rate);
    grossByRate.set(key, (grossByRate.get(key) || 0) + amt);
  }
  return [...grossByRate.entries()]
    .map(([rate, gross]) => ({
      rate,
      vat: lineVat(gross, rate),
      base: Math.round(gross * 100) / 100,
      label: `${rate}%`,
    }))
    .sort((a, b) => b.base - a.base);
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
