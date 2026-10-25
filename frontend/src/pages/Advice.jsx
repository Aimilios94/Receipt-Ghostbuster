import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api.js";
import { money, monthLabel, currentMonth, latestMonth, pct } from "../lib/format.js";
import { Card, Button, Badge, Loading, ErrorBanner, Empty } from "../components/ui.jsx";
import { Icon } from "../components/icons.jsx";
import { useToast } from "../components/toast.jsx";

// Last 6 months for the picker (same helper shape as MonthlyClose).
function recentMonths(n = 6) {
  const out = [];
  const d = new Date();
  for (let i = 0; i < n; i++) {
    const m = new Date(d.getFullYear(), d.getMonth() - i, 1);
    out.push(`${m.getFullYear()}-${String(m.getMonth() + 1).padStart(2, "0")}`);
  }
  return out;
}

// Categories that never carry a budget / spend nudge.
const SKIP_CATEGORIES = new Set(["Income", "Uncategorized"]);

const SEVERITY_TONE = { alert: "red", warning: "amber", info: "muted" };

// DOM-id-safe slug for a category name ("Dining & Cafes" -> "Dining-Cafes").
const slug = (name) => (name || "").replace(/[^a-z0-9]+/gi, "-");

export default function Advice() {
  const [month, setMonth] = useState(currentMonth());
  const [picked, setPicked] = useState(false);
  const qc = useQueryClient();
  const toast = useToast();

  // Default to the latest month that has data (until the user picks one).
  const { data: expenses } = useQuery({ queryKey: ["expenses"], queryFn: () => api.listExpenses() });
  useEffect(() => {
    if (!picked && expenses?.length) {
      const m = latestMonth(expenses);
      if (m) setMonth(m);
    }
  }, [expenses, picked]);

  const closeQ = useQuery({ queryKey: ["close", month], queryFn: () => api.close(month) });
  const catsQ = useQuery({ queryKey: ["categories"], queryFn: () => api.categories() });
  const insightsQ = useQuery({ queryKey: ["insights", month], queryFn: () => api.insights(month) });

  const dismiss = useMutation({
    mutationFn: (id) => api.dismissInsight(id, true),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["insights", month] });
      toast("Insight dismissed", "ok");
    },
    onError: (e) => toast(e.message || "Could not dismiss", "err"),
  });

  // "Adjust budget" on a nudge scrolls to and focuses that category's input.
  const focusBudget = (name) => {
    const el = document.getElementById(`budget-${slug(name)}`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    setTimeout(() => el.focus(), 300);
  };

  const isLoading = closeQ.isLoading || insightsQ.isLoading || catsQ.isLoading;
  const error = closeQ.error || insightsQ.error || catsQ.error;

  const byCategory = closeQ.data?.by_category || {};
  const insights = insightsQ.data || [];
  const budgeted = (catsQ.data || []).filter(
    (c) => c.budget_amount != null && !SKIP_CATEGORIES.has(c.name)
  );

  // Summary figures (all computed server-side; we only sum the insight rows).
  const nudgeCount = insights.length;
  const totalOver = insights
    .filter((i) => i.kind === "over_budget")
    .reduce((s, i) => s + Number(i.amount || 0), 0);
  const potentialSavings = insights
    .filter((i) => i.kind === "unused_subscription")
    .reduce((s, i) => s + Number(i.amount || 0), 0);

  return (
    <div className="rise">
      <div className="page-head">
        <div>
          <h1 className="page-title">Advice</h1>
          <div className="page-sub">
            Budget-vs-actual and rule-based nudges — every figure computed in code, no guesses.
          </div>
        </div>
        <div className="head-actions">
          <select
            className="select"
            style={{ width: 170 }}
            value={month}
            onChange={(e) => {
              setPicked(true);
              setMonth(e.target.value);
            }}
          >
            {recentMonths().map((m) => (
              <option key={m} value={m}>
                {monthLabel(m)}
              </option>
            ))}
          </select>
        </div>
      </div>

      <ErrorBanner error={error} />

      {isLoading ? (
        <Loading label="Working out your advice…" />
      ) : (
        <>
          <div className="grid grid-stats" style={{ marginBottom: 18 }}>
            <SummaryStat label="Active nudges" value={nudgeCount} />
            <SummaryStat
              label="Over budget"
              value={money(totalOver)}
              tone={totalOver > 0 ? "red" : undefined}
            />
            <SummaryStat
              label="Potential savings / yr"
              value={money(potentialSavings)}
              tone={potentialSavings > 0 ? "green" : undefined}
            />
          </div>

          <div className="grid grid-2" style={{ marginBottom: 18, alignItems: "start" }}>
            {/* Insights feed */}
            <Card className="card-pad">
              <div className="card-head">
                <div>
                  <div className="card-title">Insights</div>
                  <div className="card-desc">Nudges for {monthLabel(month)}.</div>
                </div>
              </div>
              {insights.length ? (
                insights.map((i) => (
                  <InsightRow
                    key={i.id}
                    insight={i}
                    onDismiss={() => dismiss.mutate(i.id)}
                    onAdjustBudget={() => focusBudget(i.category)}
                    busy={dismiss.isPending}
                  />
                ))
              ) : (
                <Empty icon={<Icon.check size={26} />}>
                  Nothing to flag — you're on budget and nothing's drifting.
                </Empty>
              )}
            </Card>

            {/* Budget vs actual + editor */}
            <Card className="card-pad">
              <div className="card-head">
                <div>
                  <div className="card-title">Budget vs actual</div>
                  <div className="card-desc">Set a monthly budget per category.</div>
                </div>
              </div>
              <BudgetEditor
                categories={(catsQ.data || []).filter((c) => !SKIP_CATEGORIES.has(c.name))}
                byCategory={byCategory}
                month={month}
              />
            </Card>
          </div>

          {budgeted.length === 0 ? (
            <Card className="card-pad">
              <Empty icon={<Icon.advice size={26} />}>
                Set a budget on a category above to start tracking budget-vs-actual.
              </Empty>
            </Card>
          ) : null}
        </>
      )}
    </div>
  );
}

function SummaryStat({ label, value, tone }) {
  return (
    <Card className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value num" style={tone ? { color: `var(--${tone})` } : undefined}>
        {value}
      </div>
    </Card>
  );
}

function InsightRow({ insight, onDismiss, onAdjustBudget, busy }) {
  const tone = SEVERITY_TONE[insight.severity] || "muted";
  const isSub = insight.kind === "unused_subscription";
  return (
    <div className="exc">
      <span className={`exc-ico ${tone === "red" ? "red" : "amber"}`}>
        {isSub ? <Icon.refund size={16} /> : <Icon.warn size={16} />}
      </span>
      <div className="exc-body">
        <div className="exc-kind">
          {insight.title}
          <Badge tone={tone}>{insight.severity}</Badge>
        </div>
        <div className="exc-detail">{insight.detail}</div>
      </div>
      <div className="exc-actions">
        {isSub ? (
          // One click to the money-saving action: draft the cancellation in Refund Hunter.
          <Link
            to={`/refunds?focus=${encodeURIComponent(insight.subject)}`}
            className="btn btn-sm"
            title="Draft a cancellation email in Refund Hunter"
          >
            Cancel this
          </Link>
        ) : (
          <>
            <Link
              to={`/ledger?category=${encodeURIComponent(insight.category)}`}
              className="btn btn-sm"
              title="See the expenses in this category"
            >
              View category
            </Link>
            <Button size="sm" onClick={onAdjustBudget} disabled={busy} title="Edit this category's budget">
              Adjust budget
            </Button>
          </>
        )}
        <Button size="sm" onClick={onDismiss} disabled={busy}>
          Dismiss
        </Button>
      </div>
    </div>
  );
}

function BudgetEditor({ categories, byCategory, month }) {
  const qc = useQueryClient();
  const toast = useToast();
  const save = useMutation({
    mutationFn: ({ id, amount }) => api.setCategoryBudget(id, amount),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["categories"] });
      qc.invalidateQueries({ queryKey: ["insights", month] });
      toast("Budget saved", "ok");
    },
    onError: (e) => toast(e.message || "Could not save budget", "err"),
  });

  if (!categories.length) return <Empty>No categories yet.</Empty>;

  return (
    <div>
      {categories.map((c) => (
        <BudgetRow
          key={c.id}
          category={c}
          actual={Number(byCategory[c.name] || 0)}
          onSave={(amount) => save.mutate({ id: c.id, amount })}
          busy={save.isPending}
        />
      ))}
    </div>
  );
}

function BudgetRow({ category, actual, onSave, busy }) {
  const [value, setValue] = useState(
    category.budget_amount != null ? String(category.budget_amount) : ""
  );
  // Keep the input in sync if the stored budget changes elsewhere.
  useEffect(() => {
    setValue(category.budget_amount != null ? String(category.budget_amount) : "");
  }, [category.budget_amount]);

  const budget = value === "" ? null : Number(value);
  const over = budget != null && budget > 0 && actual > budget;
  const near = budget != null && budget > 0 && !over && actual >= budget * 0.8;
  const tone = over ? "red" : near ? "amber" : "green";
  const ratio = budget && budget > 0 ? pct(actual, budget) : null;

  const commit = () => {
    const next = value === "" ? null : Number(value);
    const current = category.budget_amount != null ? Number(category.budget_amount) : null;
    if (next === current) return; // no change
    if (next != null && (Number.isNaN(next) || next < 0)) return;
    onSave(next);
  };

  return (
    <div className="bud-row">
      <div className="bud-main">
        <span className="bud-name">{category.name}</span>
        {budget != null && budget > 0 ? (
          <Badge tone={tone}>{ratio}%</Badge>
        ) : null}
      </div>
      <div className="bud-track">
        {ratio != null ? (
          <span
            className="bud-fill"
            style={{ width: `${Math.min(100, ratio)}%`, background: `var(--${tone})` }}
          />
        ) : null}
      </div>
      <div className="bud-figs num">
        {money(actual)}
        <span className="bud-of"> of </span>
        <input
          id={`budget-${slug(category.name)}`}
          className="input num bud-input"
          inputMode="decimal"
          placeholder="—"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
          disabled={busy}
          aria-label={`${category.name} monthly budget`}
        />
      </div>
    </div>
  );
}
