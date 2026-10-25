"""Chatbot (v0.5) — tool-calling over the fixed analytics surface.

The model interprets the question, selects and parameterises analytics tools, and
phrases the computed result — it never does the math itself (see analytics.py, [D1]).
`dispatch_tool` is pure (data-in, dict-out) so it's unit-testable without the LLM;
`answer_question` runs the OpenAI tool-calling loop.
"""
from __future__ import annotations

import datetime
import json
from typing import Any, Callable

from ..config import Settings
from . import analytics, monitoring
from .llm_trace import wrap_openai_if_enabled

MAX_TOOL_HOPS = 5

SYSTEM_PROMPT = """You are a friendly, read-only money assistant for Receipt Ghostbuster.
Answer questions about the user's OWN ledger ONLY by calling the provided analytics tools.
Every number in your answer MUST come from a tool result — never compute, estimate, or infer
a figure yourself. Today's date is {today}; months are 'YYYY-MM' (the current month is
{this_month}). Amounts are in euros.

HOW TO WRITE THE ANSWER (important):
- Write for a normal person, in plain, natural language. NEVER mention tool or function names,
  argument names, or raw result keys (e.g. don't write "spend_by_day", "max_day", "top_expenses",
  "per the tool result", or JSON). The interface already shows which calculations ran.
- Show money with the € sign (e.g. €48.24) and write dates naturally (e.g. "3 October 2026").
- When you report a single day or a single expense, say WHAT it was: name the vendor and the
  category. If the user asks what an expense/day contains, give the full detail — vendor, amount,
  category, the VAT, and the named products bought (the expense-details tool returns them). If a
  receipt has no itemised products, say so. For "what do I buy most often", use the top-products tool.
- LISTS OVER A DATE RANGE: when the user asks to list/show their expenses between two dates, call the
  expenses-in-range tool and give a SHORT summary only (e.g. "Between 5 and 15 October you spent €X across
  N expenses at M vendors."). Do NOT enumerate every expense in prose — the interface renders a grouped,
  expandable list (by vendor, with totals) below your reply.
- CSV / BANK STATEMENT / TRANSACTIONS for a date range: call the bank-transactions tool and give a short
  summary (totals + count). The interface shows the transactions as a table with a Download CSV button below
  your reply, so don't paste the rows into your text and don't tell the user to go find a file.
- SHOWING A RECEIPT: when the user asks to see / open / show a receipt, call the get-receipt tool.
  The interface WILL display the receipt image right below your reply automatically — so just say
  something like "Here's the receipt for Pingo Doce on 3 October 2026:" and stop. NEVER tell the user
  to open the app, navigate to a page, tap a thumbnail, or take screenshots — you can show it directly.
- Be direct and action-oriented. Answer the question asked. Do NOT end with offers like "would you
  like me to…" or ask a clarifying question unless the request is genuinely ambiguous (e.g. no month
  is given and it changes the answer). Be concise; use a short list when there are several items.

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
        "name": "spend_by_day", "description": "Spend per day in a month, with the highest and lowest spend days.",
        "parameters": {"type": "object", "properties": {"month": {"type": "string", "description": "YYYY-MM"}}, "required": ["month"]}}},
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
        "name": "spend_by_vendor", "description": "Spend grouped by vendor/merchant (optionally one month).",
        "parameters": {"type": "object", "properties": {"month": {"type": "string", "description": "YYYY-MM, optional"}}}}},
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
        "spend_by_day": lambda: analytics.spend_by_day(exp, args["month"]),
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
        "spend_by_vendor": lambda: analytics.spend_by_vendor(exp, args.get("month")),
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


def _system_prompt(today: datetime.date | None = None) -> str:
    today = today or datetime.date.today()
    return SYSTEM_PROMPT.format(today=today.isoformat(), this_month=today.strftime("%Y-%m"))


def _receipt_attachments(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull receipt images out of a tool result so the UI can display them inline."""
    out = []
    for e in (result.get("expenses") or []):
        url = e.get("receipt_url")
        if url:
            label = " · ".join(x for x in [e.get("vendor"), e.get("date")] if x)
            out.append({"type": "receipt", "url": url, "label": label})
    return out


def _attachments_for(tool_name: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the rich UI attachment(s) a tool's result should display below the reply:
    receipt images, an expandable grouped expense list, or a transactions table/CSV."""
    if tool_name == "get_receipt":
        return _receipt_attachments(result)
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


def answer_question(
    message: str,
    history: list[dict[str, str]],
    data: dict[str, Any],
    settings: Settings,
    *,
    today: datetime.date | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    """Run the tool-calling loop and return {answer, used_tools, grounded}.

    `used_tools` records each analytics call (name + args) so the answer is
    auditable; `grounded` is true when at least one tool produced the numbers.
    `client` is an optional injected OpenAI-compatible client (used by the eval
    harness / tests to drive the loop offline); when None the live client is built.
    """
    if client is None:
        from openai import OpenAI

        client = wrap_openai_if_enabled(OpenAI(api_key=settings.openai_api_key))
    token_arg = (
        {"max_completion_tokens": 4000}
        if settings.openai_model.lower().startswith(("gpt-5", "o1", "o3", "o4"))
        else {"max_tokens": 1000}
    )

    messages: list[dict[str, Any]] = [{"role": "system", "content": _system_prompt(today)}]
    for turn in history[-8:]:  # a little context, capped
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": message})

    used_tools: list[dict[str, Any]] = []
    attachments: list[dict[str, str]] = []

    def _add_attachments(items: list[dict[str, Any]]) -> None:
        seen = {(a.get("url") or a.get("title")) for a in attachments}
        for a in items:
            key = a.get("url") or a.get("title")
            if key not in seen:
                attachments.append(a)
                seen.add(key)

    for _ in range(MAX_TOOL_HOPS):
        resp = client.chat.completions.create(
            model=settings.openai_model, messages=messages, tools=TOOLS, tool_choice="auto", **token_arg
        )
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return {"answer": msg.content or "", "used_tools": used_tools, "grounded": bool(used_tools), "attachments": attachments}
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
            _add_attachments(_attachments_for(tc.function.name, result))
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})

    # Ran out of hops — ask once more for a final answer without tools.
    resp = client.chat.completions.create(model=settings.openai_model, messages=messages, **token_arg)
    return {
        "answer": resp.choices[0].message.content or "",
        "used_tools": used_tools,
        "grounded": bool(used_tools),
        "attachments": attachments,
    }
