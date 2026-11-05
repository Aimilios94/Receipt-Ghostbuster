"""Chatbot (v0.5) — tool-calling over the fixed analytics surface.

The model interprets the question, selects and parameterises analytics tools, and
phrases the computed result — it never does the math itself (see analytics.py, [D1]).
`dispatch_tool` is pure (data-in, dict-out) so it's unit-testable without the LLM;
`answer_question` runs the OpenAI tool-calling loop.
"""
from __future__ import annotations

import datetime
import json
import time
from typing import Any, Callable

from ..config import Settings
from . import analytics, chat_cache, monitoring
from . import breakdown as breakdown_service
from .llm_trace import LlmCall, aggregate, wrap_openai_if_enabled

MAX_TOOL_HOPS = 5

SYSTEM_PROMPT = """You are a friendly, read-only money assistant for Receipt Ghostbuster.
Answer questions about the user's OWN ledger ONLY by calling the provided analytics tools.
Every number in your answer MUST come from a tool result — never compute, estimate, or infer
a figure yourself. Today's date is {today}; months are 'YYYY-MM' (the current month is
{this_month}). Amounts are in euros.

HOW TO WRITE THE ANSWER (important):
- Lead with the answer in ONE or TWO short sentences of plain language. That is your whole reply.
- The interface draws the details below your reply, directly from the calculations: ranked days,
  categories, vendors and products with bars; month comparisons; expense lists that open to their
  products, VAT and receipt; transfers; transaction tables; receipt images. So NEVER repeat those rows:
  no lists, no per-expense or per-product lines, no notes stored on an expense, no markdown.
- Never mention tool or function names, argument names, raw result keys or JSON. Show money with the
  € sign (e.g. €48.24) and write dates naturally (e.g. "3 October 2026").
- Say what the figure means when it helps, using only figures from the results. Good: "Your 3 biggest
  days total €104.40, 54.8% of October's €190.47." Good: "Groceries was your biggest category in October
  at €78.10, out of €190.47." Bad: naming every category, day, vendor or expense with its amount. Bad:
  "shown below" with no fact: always state the main fact first.
- Be direct. No offers like "would you like me to…" and no instructions to open a page or find a file:
  the interface already shows receipts and a Download CSV button.

CHOOSING THE CALCULATION:
- Month: a month the user names wins, even misspelled ("octomber", "oktomber" mean October). Never ask
  them to confirm it. If they name none, use the most recent month with data ({latest_month}) and say
  which month you used. "This month" alone means {this_month}.
- "Most expenses" or "most purchases" means the NUMBER of expenses: use the by-day tool with rank_by
  "count". "Spent the most" means the amount.
- For the top N days or the busiest day, call the by-day tool (top N, or top 1 with rank_by "count"). Don't
  also fetch those days' expense details: the card already lists each day's expenses.
- "What did I buy / what was in that expense": call the expense-details tool and give the vendor, date,
  amount and number of items. Mention a number of items only for this. A receipt can mix VAT rates: when no single rate is given, report the
  total VAT or the per-rate figures, never one rate for the whole receipt.
- "What do I buy most often": use the top-products tool.
- Spend at one vendor: the by-vendor tool with that vendor's name, so the card shows only that vendor.
- Comparing months: a month whose has_data is false has no expenses recorded, which isn't the same as
  spending nothing. Say nothing is recorded for that month, and don't describe an increase or decrease.
  If category_found is false, say that category isn't in the ledger and name the closest known ones.
  Never report it as €0.
- Lists over a date range: the expenses-in-range tool. CSV, bank statement or transactions for a range:
  the bank-transactions tool. Showing a receipt: the get-receipt tool, then just say "Here's the receipt
  for Pingo Doce on 3 October 2026."
- Ask a question back only when no reasonable reading exists.

SUBSCRIPTIONS (strict rules — never break these):
- CASH expenses are NEVER subscriptions and are excluded from reconciliation entirely. Never list a cash
  expense as a subscription or a possible one.
- One-off consumption — groceries, dining & cafes, transport & fuel, tobacco, travel, pharmacy — are NOT
  subscriptions. Never present them as candidates.
- A subscription is a recurring SERVICE paid by card/online. For "which of my payments might be a
  subscription?", call the subscription-candidates tool (it already applies these exclusions) or, for
  already-detected ones, active-subscriptions. Confirming a subscription needs ≥3 same-amount charges
  across months — with a single month you can only flag candidates, say so plainly.

If no tool can answer the question, say you can't answer it from their ledger rather than guessing.
You report what the ledger says; you do NOT give financial or tax advice."""

# OpenAI tool schemas. Each maps to an analytics.* function via _DISPATCH below.
TOOLS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "total_spend", "description": "Total spend in a month.",
        "parameters": {"type": "object", "properties": {"month": {"type": "string", "description": "YYYY-MM"}}, "required": ["month"]}}},
    {"type": "function", "function": {
        "name": "spend_by_day", "description": "Spend and number of expenses per day in a month: the highest and lowest spend days, the busiest day by count, and the days ranked by amount or count. Use for 'which day did I spend the most', 'my top 3 days' and 'which day had the most expenses'.",
        "parameters": {"type": "object", "properties": {
            "month": {"type": "string", "description": "YYYY-MM"},
            "top": {"type": "integer", "description": "keep only the first N ranked days, optional"},
            "rank_by": {"type": "string", "enum": ["amount", "count"], "description": "'amount' (default) or 'count' for the number of expenses"}},
            "required": ["month"]}}},
    {"type": "function", "function": {
        "name": "spend_by_category", "description": "Spend grouped by category for a month.",
        "parameters": {"type": "object", "properties": {"month": {"type": "string", "description": "YYYY-MM"}}, "required": ["month"]}}},
    {"type": "function", "function": {
        "name": "compare_category", "description": "Compare one category's spend between two months.",
        "parameters": {"type": "object", "properties": {
            "category": {"type": "string"}, "month_a": {"type": "string", "description": "YYYY-MM"},
            "month_b": {"type": "string", "description": "YYYY-MM"}}, "required": ["category", "month_a", "month_b"]}}},
    {"type": "function", "function": {
        "name": "top_expenses", "description": "The N largest expenses in a month.",
        "parameters": {"type": "object", "properties": {
            "month": {"type": "string", "description": "YYYY-MM"}, "n": {"type": "integer", "description": "how many, default 5"}},
            "required": ["month"]}}},
    {"type": "function", "function": {
        "name": "expense_details", "description": "Full detail of specific expenses (vendor, category, amount, VAT, line items, whether a receipt photo is on file) — use for 'what was that expense / what did I buy that day?'. Filter by date (YYYY-MM-DD), vendor, and/or month.",
        "parameters": {"type": "object", "properties": {
            "date": {"type": "string", "description": "YYYY-MM-DD, optional"},
            "vendor": {"type": "string", "description": "vendor name substring, optional"},
            "month": {"type": "string", "description": "YYYY-MM, optional"}}}}},
    {"type": "function", "function": {
        "name": "expenses_in_range", "description": "All expenses between two dates (inclusive), grouped by vendor. Use for 'list/show my expenses between X and Y'. The interface renders a grouped, expandable list below your reply.",
        "parameters": {"type": "object", "properties": {
            "date_from": {"type": "string", "description": "YYYY-MM-DD"},
            "date_to": {"type": "string", "description": "YYYY-MM-DD"}}, "required": ["date_from", "date_to"]}}},
    {"type": "function", "function": {
        "name": "bank_transactions", "description": "Bank-statement transactions between two dates (inclusive), as a table. Use for 'show/send me the CSV/bank statement/transactions for X to Y'. The interface renders a table with a Download CSV button below your reply.",
        "parameters": {"type": "object", "properties": {
            "date_from": {"type": "string", "description": "YYYY-MM-DD"},
            "date_to": {"type": "string", "description": "YYYY-MM-DD"}}, "required": ["date_from", "date_to"]}}},
    {"type": "function", "function": {
        "name": "get_receipt", "description": "Fetch the receipt photo(s) for matching expenses so the interface can DISPLAY the image to the user. Use whenever the user asks to see/open/show a receipt. Filter by date (YYYY-MM-DD), vendor, and/or month.",
        "parameters": {"type": "object", "properties": {
            "date": {"type": "string", "description": "YYYY-MM-DD, optional"},
            "vendor": {"type": "string", "description": "vendor name substring, optional"},
            "month": {"type": "string", "description": "YYYY-MM, optional"}}}}},
    {"type": "function", "function": {
        "name": "top_products", "description": "The products bought most often (by number of appearances), optionally filtered to one vendor and/or month. Use for 'what do I buy most at X?'.",
        "parameters": {"type": "object", "properties": {
            "vendor": {"type": "string", "description": "vendor name substring, optional"},
            "month": {"type": "string", "description": "YYYY-MM, optional"},
            "n": {"type": "integer", "description": "how many, default 10"}}}}},
    {"type": "function", "function": {
        "name": "vat_paid", "description": "Total VAT paid in a period: 'YYYY-MM' for a month or 'YYYY' for a year.",
        "parameters": {"type": "object", "properties": {"period": {"type": "string"}}, "required": ["period"]}}},
    {"type": "function", "function": {
        "name": "active_subscriptions", "description": "The user's already-detected subscriptions and their annual cost.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "subscription_candidates", "description": "Merchants that COULD be a recurring subscription (non-cash card/online purchases only; cash and one-off consumption like groceries/dining are excluded). Use for 'which of my payments might be a subscription?'. Can't confirm recurrence from one month — flags candidates only.",
        "parameters": {"type": "object", "properties": {"month": {"type": "string", "description": "YYYY-MM, optional"}}}}},
    {"type": "function", "function": {
        "name": "spend_by_vendor", "description": "Spend grouped by vendor/merchant. Optionally one month, and pass vendor when the question is about one specific vendor.",
        "parameters": {"type": "object", "properties": {
            "month": {"type": "string", "description": "YYYY-MM, optional"},
            "vendor": {"type": "string", "description": "vendor name, for a question about one vendor, optional"}}}}},
    {"type": "function", "function": {
        "name": "transfers_summary", "description": "Money sent to/received from people (third parties) and own-account movements (optionally one month).",
        "parameters": {"type": "object", "properties": {"month": {"type": "string", "description": "YYYY-MM, optional"}}}}},
]


def dispatch_tool(name: str, args: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Run one analytics tool against the data bundle {expenses, bank, subscriptions}.
    Pure — no LLM, no DB. Returns the structured result (or an {error} dict)."""
    exp = data.get("expenses", [])
    bank = data.get("bank", [])
    subs = data.get("subscriptions", [])
    table: dict[str, Callable[[], dict[str, Any]]] = {
        "total_spend": lambda: analytics.total_spend(exp, args["month"]),
        "spend_by_day": lambda: analytics.spend_by_day(
            exp, args["month"], top=args.get("top"), rank_by=args.get("rank_by", "amount")
        ),
        "spend_by_category": lambda: analytics.spend_by_category(exp, args["month"]),
        "compare_category": lambda: analytics.compare_category(exp, args["category"], args["month_a"], args["month_b"]),
        "top_expenses": lambda: analytics.top_expenses(exp, args["month"], args.get("n", 5)),
        "expenses_in_range": lambda: analytics.expenses_in_range(exp, date_from=args["date_from"], date_to=args["date_to"]),
        "bank_transactions": lambda: analytics.bank_transactions_range(bank, date_from=args["date_from"], date_to=args["date_to"]),
        "expense_details": lambda: analytics.expense_details(
            exp, data.get("line_items", {}),
            date=args.get("date"), vendor=args.get("vendor"), month=args.get("month"),
        ),
        "get_receipt": lambda: analytics.expense_details(
            exp, data.get("line_items", {}),
            date=args.get("date"), vendor=args.get("vendor"), month=args.get("month"),
        ),
        "top_products": lambda: analytics.top_products(exp, vendor=args.get("vendor"), month=args.get("month"), n=args.get("n", 10)),
        "vat_paid": lambda: analytics.vat_paid(exp, args["period"]),
        "active_subscriptions": lambda: analytics.active_subscriptions(subs),
        "subscription_candidates": lambda: analytics.subscription_candidates(exp, bank, month=args.get("month")),
        "spend_by_vendor": lambda: analytics.spend_by_vendor(exp, args.get("month"), args.get("vendor")),
        "transfers_summary": lambda: analytics.transfers_summary(bank, args.get("month")),
    }
    fn = table.get(name)
    if fn is None:
        return {"error": f"unknown tool {name}"}
    try:
        return fn()
    except KeyError as exc:
        return {"error": f"missing argument {exc}"}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:200]}


def _latest_month(data: dict[str, Any], today: datetime.date) -> str:
    months = [str(e.get("expense_date") or "")[:7] for e in data.get("expenses", [])]
    return max((m for m in months if m), default=today.strftime("%Y-%m"))


def _system_prompt(today: datetime.date | None = None, data: dict[str, Any] | None = None) -> str:
    today = today or datetime.date.today()
    return SYSTEM_PROMPT.format(
        today=today.isoformat(),
        this_month=today.strftime("%Y-%m"),
        latest_month=_latest_month(data or {}, today),
    )


def _receipt_attachments(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull receipt images out of a tool result so the UI can display them inline."""
    out = []
    for e in (result.get("expenses") or []):
        url = e.get("receipt_url")
        if url:
            label = " · ".join(x for x in [e.get("vendor"), e.get("date")] if x)
            out.append({"type": "receipt", "url": url, "label": label})
    return out


_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December")


def _month_label(month: str | None) -> str:
    try:
        return f"{_MONTHS[int(month[5:7]) - 1]} {month[:4]}"
    except (TypeError, ValueError, IndexError):
        return "All time"


def _day_label(date: str | None) -> str:
    try:
        return f"{int(date[8:10])} {_MONTHS[int(date[5:7]) - 1][:3]}"
    except (TypeError, ValueError, IndexError):
        return str(date or "")


def _ranking(title: str, subtitle: str, rows: list[dict[str, Any]], *, by: str = "total",
             total: Any = None) -> dict[str, Any]:
    """A ranked card. `bar` is each row's size relative to the largest; every figure comes
    straight from a calculation, so the model never retypes it."""
    largest = max((float(r.get(by) or 0) for r in rows), default=0.0)
    for r in rows:
        r["bar"] = round(float(r.get(by) or 0) / largest, 4) if largest else 0.0
    return {"type": "ranking", "title": title, "subtitle": subtitle, "total": total, "rows": rows}


def _attachments_for(
    tool_name: str, result: dict[str, Any], data: dict[str, Any] | None = None, args: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Build the card(s) a tool's result should display below the reply. The model writes
    only the summary; the rows here are computed, so a long answer stays readable."""
    data, args = data or {}, args or {}
    if "error" in result:
        return []
    if tool_name == "get_receipt":
        return _receipt_attachments(result)
    if tool_name == "total_spend":
        month = result.get("month")
        return [{
            "type": "total",
            "title": "Total spend",
            "subtitle": _month_label(month),
            "total": result.get("total"),
            "expenses": analytics.expense_rows(analytics.spend_rows(data.get("expenses", []), month)),
        }]
    if tool_name == "vat_paid":
        period = str(result.get("period") or "")
        return [{
            "type": "total",
            "title": "VAT paid",
            "subtitle": _month_label(period) if len(period) == 7 else period,
            "total": result.get("vat"),
            "amount_key": "vat_amount",
            "expenses": analytics.vat_rows(data.get("expenses", []), period),
        }]
    if tool_name == "spend_by_day":
        spend = analytics.spend_rows(data.get("expenses", []), result.get("month"))
        ranked = result.get("ranked") or {}
        by_count = ranked.get("by") == "count"
        days = ranked.get("days") or []
        if by_count:
            title = "Days by number of expenses" if len(days) != 1 else "Day with the most expenses"
        elif args.get("top"):
            title = "Top day" if len(days) == 1 else f"Top {len(days)} days"
        else:
            title = "Spending by day"
        rows = [
            {
                "label": _day_label(d["date"]),
                "total": d["total"],
                "count": d["count"],
                "expenses": analytics.expense_rows(
                    [e for e in spend if str(e.get("expense_date") or "")[:10] == d["date"]]
                ),
            }
            for d in days
        ]
        return [_ranking(title, _month_label(result.get("month")), rows, by="count" if by_count else "total",
                         total=result.get("total"))]
    if tool_name == "spend_by_category":
        spend = analytics.spend_rows(data.get("expenses", []), result.get("month"))
        rows = [
            {
                "label": name,
                "total": float(amount),
                "count": len(matching := [e for e in spend if (e.get("category") or "Uncategorized") == name]),
                "expenses": analytics.expense_rows(matching),
            }
            for name, amount in sorted((result.get("by_category") or {}).items(), key=lambda kv: float(kv[1]), reverse=True)
        ]
        return [_ranking("Spending by category", _month_label(result.get("month")), rows, total=result.get("total"))]
    if tool_name == "spend_by_vendor":
        spend = analytics.spend_rows(data.get("expenses", []), result.get("month"))
        rows = [
            {
                "label": v["vendor"],
                "total": v["total"],
                "count": v["count"],
                "expenses": analytics.expense_rows(
                    [e for e in spend if (str(e.get("vendor") or "").strip() or "Unknown").lower() == v["vendor"].lower()]
                ),
            }
            for v in result.get("vendors") or []
        ]
        name = rows[0]["label"] if len(rows) == 1 else result.get("vendor")
        title = f"Spending at {name}" if result.get("vendor") else "Spending by vendor"
        return [_ranking(title, _month_label(result.get("month")), rows,
                         total=round(sum(r["total"] for r in rows), 2))]
    if tool_name == "top_products":
        rows = [
            {
                "label": analytics.display_product(p["product"]),
                "total": p["total"],
                "count": p["count"],
                "expenses": analytics.product_rows(
                    data.get("expenses", []), p["product"], vendor=result.get("vendor"), month=result.get("month")
                ),
            }
            for p in result.get("products") or []
        ]
        scope = " · ".join(x for x in [result.get("vendor"), _month_label(result.get("month")) if result.get("month") else None] if x)
        return [{**_ranking("Most bought products", scope or "All receipts", rows, by="count"), "count_unit": "times"}]
    if tool_name == "transfers_summary":
        month = result.get("month")
        bank = data.get("bank", [])
        people = breakdown_service.third_party_breakdown(
            [t for t in bank if not month or str(t.get("txn_date") or "")[:7] == month]
        )
        scope = _month_label(month)
        out = []
        for key, title, total_key in (("sent", "Money sent to people", "total_sent"),
                                      ("received", "Money received from people", "total_received")):
            rows = [
                {"label": r["name"], "total": r["total"], "count": r["count"], "transactions": r["items"]}
                for r in people.get(key) or []
            ]
            if rows:
                out.append({**_ranking(title, scope, rows, total=people.get(total_key)), "count_unit": "transfers"})
        return out
    if tool_name == "compare_category":
        if not result.get("category_found"):
            return []
        return [{
            "type": "comparison",
            "title": result.get("category"),
            "a": {"label": _month_label(result.get("month_a")),
                  "total": result.get("total_a") if result.get("month_a_has_data") else None,
                  "expenses": analytics.category_rows(data.get("expenses", []), result.get("category"), result.get("month_a"))},
            "b": {"label": _month_label(result.get("month_b")),
                  "total": result.get("total_b") if result.get("month_b_has_data") else None,
                  "expenses": analytics.category_rows(data.get("expenses", []), result.get("category"), result.get("month_b"))},
            "delta": result.get("delta"),
            "pct_change": result.get("pct_change"),
        }]
    if tool_name == "top_expenses":
        items = result.get("items") or []
        return [{
            "type": "expense_list",
            "title": f"Top {len(items)} expenses",
            "subtitle": _month_label(result.get("month")),
            "expenses": items,
        }]
    if tool_name == "expense_details":
        items = result.get("expenses") or []
        if not items:
            return []
        scope = " · ".join(x for x in [result.get("vendor"), _day_label(result.get("date")) if result.get("date") else None,
                                       _month_label(result.get("month")) if result.get("month") else None] if x)
        card = {
            "type": "expense_list",
            "title": "Expense" if len(items) == 1 else f"{len(items)} expenses",
            "subtitle": scope,
            "key": f"details:{scope}",
            "expenses": [{k: e.get(k) for k in ("id", "date", "vendor", "category", "amount", "source")} for e in items],
        }
        if len(items) == 1 and items[0].get("products"):
            card["products"] = [
                {"name": analytics.display_product(p["description"]), "amount": p.get("amount"), "vat_rate": p.get("vat_rate")}
                for p in items[0]["products"]
            ]
        return [card]
    if tool_name == "expenses_in_range":
        return [{
            "type": "expense_groups",
            "title": f"Expenses {result.get('date_from')} to {result.get('date_to')}",
            "total": result.get("total"),
            "count": result.get("count"),
            "groups": result.get("groups") or [],
        }]
    if tool_name == "bank_transactions":
        rows = result.get("rows") or []
        return [{
            "type": "table",
            "title": f"Bank transactions {result.get('date_from')} to {result.get('date_to')}",
            "columns": ["Date", "Description", "Type", "Amount", "Balance"],
            "rows": [[r["date"], r["description"], r["type"], r["amount"], r["balance"]] for r in rows],
            "filename": f"transactions_{result.get('date_from')}_{result.get('date_to')}.csv",
            "total_out": result.get("total_out"),
            "total_in": result.get("total_in"),
        }]
    return []


def _drop_covered_lists(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A ranking already lists its rows' expenses and total, so an expense list or a total card
    repeating them adds only noise. One showing a single receipt's products stays: it answers
    what was bought."""
    covered = {
        e.get("id")
        for a in attachments if a.get("type") == "ranking"
        for r in a.get("rows", []) for e in r.get("expenses", [])
    }
    if any(a.get("type") == "ranking" for a in attachments):
        attachments = [a for a in attachments if a.get("type") != "total"]
    product_cards = [a for a in attachments if a.get("type") == "expense_list" and a.get("products")]
    repeats = [
        a for a in attachments
        if a.get("type") == "expense_list"
        and all(e.get("id") in covered for e in a.get("expenses", []))
        and not (len(product_cards) == 1 and a is product_cards[0])
    ]
    return [a for a in attachments if a not in repeats]


def answer_question(
    message: str,
    history: list[dict[str, str]],
    data: dict[str, Any],
    settings: Settings,
    *,
    today: datetime.date | None = None,
    client: Any | None = None,
    use_cache: bool = False,
    cache_scope: str = "",
    on_trace: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run the tool-calling loop and return {answer, used_tools, grounded}.

    `used_tools` records each analytics call (name + args) so the answer is
    auditable; `grounded` is true when at least one tool produced the numbers.
    `client` is an optional injected OpenAI-compatible client (used by the eval
    harness / tests to drive the loop offline); when None the live client is built.
    `use_cache` returns a cached answer for a repeated single-shot question over an
    unchanged ledger (the key includes a ledger fingerprint, so it self-invalidates);
    only the app path enables it, so the eval/tests always get a fresh run. `cache_scope`
    is the user id — part of the key. `on_trace` receives one record per question (latency,
    tokens, estimated cost, calculations used, never the question itself), so the router
    can persist it while this module stays DB-free.
    """
    started = time.perf_counter()
    calls: list[LlmCall] = []
    used_tools: list[dict[str, Any]] = []

    def _report(*, tools: list[dict[str, Any]], cached: bool = False, error: str | None = None) -> None:
        if on_trace is None:
            return
        trace = aggregate(calls, provider="openai", model=settings.openai_model, kind="chat")
        trace.update(
            latency_ms=int((time.perf_counter() - started) * 1000),
            success=error is None,
            error=error,
            cached=cached,
            tools=[t.get("name") for t in tools],
        )
        on_trace(trace)

    # Only a fresh, single-shot question is safely cacheable — multi-turn context
    # (history) makes the answer non-idempotent.
    cacheable = use_cache and not history
    if cacheable:
        hit = chat_cache.get_cached(message, data, settings.openai_model, cache_scope)
        if hit is not None:
            _report(tools=hit.get("used_tools") or [], cached=True)
            return {**hit, "cached": True}

    if client is None:
        from openai import OpenAI

        client = wrap_openai_if_enabled(OpenAI(api_key=settings.openai_api_key))
    token_arg = (
        {"max_completion_tokens": 4000}
        if settings.openai_model.lower().startswith(("gpt-5", "o1", "o3", "o4"))
        else {"max_tokens": 1000}
    )

    messages: list[dict[str, Any]] = [{"role": "system", "content": _system_prompt(today, data)}]
    for turn in history[-8:]:  # a little context, capped
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": message})

    attachments: list[dict[str, str]] = []

    def _complete(**kwargs: Any) -> Any:
        call_started = time.perf_counter()
        trace_args = {"provider": "openai", "model": settings.openai_model, "kind": "chat", "started": call_started}
        try:
            resp = client.chat.completions.create(
                model=settings.openai_model, messages=messages, **token_arg, **kwargs
            )
        except Exception as exc:
            error = str(exc)[:200]
            calls.append(LlmCall.timed(**trace_args, success=False, error=error))
            _report(tools=used_tools, error=error)
            raise
        calls.append(LlmCall.timed(**trace_args, resp=resp))
        return resp

    def _add_attachments(items: list[dict[str, Any]]) -> None:
        seen = {(a.get("url") or a.get("key") or a.get("title")) for a in attachments}
        for a in items:
            key = a.get("url") or a.get("key") or a.get("title")
            if key not in seen:
                attachments.append(a)
                seen.add(key)

    def _finish(answer: str) -> dict[str, Any]:
        result = {"answer": answer, "used_tools": used_tools,
                  "grounded": bool(used_tools), "attachments": _drop_covered_lists(attachments)}
        if cacheable:
            chat_cache.put_cached(message, data, settings.openai_model, result, cache_scope)
        _report(tools=used_tools)
        return result

    for _ in range(MAX_TOOL_HOPS):
        resp = _complete(tools=TOOLS, tool_choice="auto")
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return _finish(msg.content or "")
        # Record the assistant's tool-call turn, then answer each tool call.
        messages.append({
            "role": "assistant", "content": msg.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ],
        })
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = dispatch_tool(tc.function.name, args, data)
            used_tools.append({"name": tc.function.name, "args": args})
            _add_attachments(_attachments_for(tc.function.name, result, data, args))
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})

    # Ran out of hops — ask once more for a final answer without tools.
    resp = _complete()
    return _finish(resp.choices[0].message.content or "")
