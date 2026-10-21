# Design — Refund Hunter chatbot (natural-language Q&A)

*Status: design only (planned as v0.5). Nothing here is built yet. This doc fixes the architecture and
the evaluation approach up front so the build stays honest and testable — the same way DECISIONS.md fixes
"why" before code.*

## Problem

The app already computes everything about a user's money onto **one ledger** (every dashboard number drills
back to its expenses — [D10](../../DECISIONS.md)). But the user still has to *find* the right screen to
answer a question. People think in questions, not dashboards:

- "Which day did I spend the most this month?"
- "Which week do I usually spend the least?"
- "How much did Groceries cost vs last month?"
- "What are my active subscriptions and their annual cost?"
- "How much VAT have I paid this quarter?"

The chatbot lets them **ask**, in plain language, over the same ledger.

## Non-negotiable principle: the AI never does the math

This extends [D1](../../DECISIONS.md) ("the AI is never trusted blindly") from extraction to Q&A. The model
must **not** free-form sum amounts, average spend, or invent a figure from the conversation. Every number in
an answer is **computed in code** by a deterministic analytics function; the model only:

1. interprets the question,
2. **selects and parameterises** the right analytics function(s) (tool-calling), and
3. phrases the computed result in natural language, citing it.

A model doing arithmetic over a list of transactions in its head is exactly the failure mode the whole
project is built against.

## Architecture: tool-calling over a fixed analytics surface

```
User question
     │
     ▼
LLM (tool-calling)  ──selects──►  analytics functions (pure, in code, unit-tested)
     │                              e.g. spend_by_day(month), spend_by_category(period),
     │                                   compare_periods(cat, a, b), top_expenses(period, n),
     ▼                                   vat_paid(period), active_subscriptions()
Grounded answer  ◄──computed numbers──
(cites the figure; declines if no tool fits)
```

- **Analytics functions** live in the backend (a new `services/analytics.py`), each pure, DB-backed through
  the existing repository, and **unit-tested** against known ledgers — so the numbers are provably right
  regardless of the model. They return structured results, not prose.
- **Tool-calling, not text-to-SQL.** A fixed, auditable function surface is safer and more testable than
  letting the model emit SQL against the user's financial DB (injection/correctness/safety risk). If the
  analytics surface ever grows beyond what's practical as hand-written tools, a *read-only, sandboxed,
  validated* query layer could be reconsidered — but tool-calling is the default.
- **Grounding & refusal.** If no tool answers the question, the assistant says so rather than guessing. It
  does not give financial/tax *advice* (that's v0.4's rule-based Advice feature, clearly scoped) — it reports
  what the ledger says.
- **Scope & safety.** Read-only over the current user's own data; no mutations, no sends; honours the same
  per-user boundary the rest of the app does.

## Evaluation (the reason to design it now)

The chatbot is highly evaluable, and in a way that mostly avoids an LLM judge:

1. **Deterministic questions have a computable exact ground truth.** "Which day had the most expenses in
   October?" has one correct answer the analytics function itself produces over a fixed test ledger. So the
   eval set is pairs of *(question, fixed ledger) → exact expected answer*, graded by **code**, no judge
   needed. This covers most real questions.
2. **Tool-selection accuracy.** Given a question, did the model call the **right** analytics function with the
   **right** arguments? Scored deterministically against a labelled expected tool-call — this is the LLM's
   actual job here, so it's the key metric.
3. **Faithfulness / grounding (LLM-as-judge, calibrated).** For open-ended phrasing, a judge checks the prose
   answer **follows from the computed numbers** (no added/changed figures). The judge is **calibrated against
   human labels** on a sample before it's trusted — an uncalibrated judge is just vibes with extra cost.
4. **Refusal correctness.** Out-of-scope / unanswerable questions should be declined, not answered — scored
   on a small adversarial set.
5. **Multi-model + cost/latency.** Reuse the `eval_models.py` pattern to compare models on tool-selection
   accuracy, latency and cost, and trace live calls to LangSmith like extraction does.

This means the chatbot ships with its own measured quality story from day one, consistent with D26/D30.

## Out of scope (initially)

Multi-turn memory beyond the current session · charts/visual answers · writing to the ledger · financial or
tax advice (separate, rule-based — see v0.4) · anything that bypasses the compute-in-code rule.
