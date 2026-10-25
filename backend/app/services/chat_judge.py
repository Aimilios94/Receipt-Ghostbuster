"""Faithfulness judge for the chatbot (v0.5 Slice 3).

The chatbot's numbers are already computed in code and graded deterministically
([D41]); what a *judge* adds is a check on the PROSE: does the sentence the model
wrote follow from the tool results, with no figure added, changed, or invented, and
no unsupported claim? This is an LLM-as-judge — and per `docs/design/chatbot.md` it
is only trusted after being **calibrated against human-verified labels**
(`eval/chatbot/calibration.json`); an uncalibrated judge is "vibes with extra cost".

Pure-ish + DB-free: `build_messages`/`parse_verdict` are offline-testable; only
`judge_faithfulness` touches the model. A parse failure is treated as `unfaithful`
(fail safe — never silently pass a prose answer we couldn't grade).
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..config import Settings
from .llm_trace import wrap_openai_if_enabled

JUDGE_SYSTEM = """You are a STRICT faithfulness grader for a money assistant.
You are given a user QUESTION, the TOOL RESULTS (the ground-truth figures computed in
code — the ONLY facts the answer may use), and the assistant's ANSWER.

Decide whether the ANSWER is FAITHFUL to the TOOL RESULTS:
- UNFAITHFUL if the answer states any amount, date, count, vendor, category or other
  figure that is NOT present in the tool results, or that CONTRADICTS them (a changed
  number, a wrong vendor/day, a miscalculated or invented total).
- UNFAITHFUL if it adds a factual claim about the user's money that the tool results
  do not support.
- FAITHFUL if every figure and claim in the answer is supported by the tool results.
  Natural paraphrase, rounding that matches, formatting, and declining to answer are
  all fine — judge the FACTS, not the wording.

All amounts in the tool results are in EUROS. Rendering a figure with a currency symbol
(e.g. "€138.99"), writing a date in words ("20 October 2026" for 2026-10-20), or otherwise
formatting/paraphrasing a value the tool provided is FAITHFUL — it is the SAME fact, not a
new one. A fact counts as supported if it appears in ANY of the tool results. Flag only a
figure or claim that is CHANGED, CONTRADICTED, or genuinely ABSENT from the tool results.

Respond with ONLY a JSON object: {"verdict": "faithful" | "unfaithful", "reason": "<one short sentence>"}."""


def build_messages(question: str, answer: str, tool_results: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The judge prompt. `tool_results` is the list of structured results the chatbot's
    tools returned (the facts the prose must match), serialised as JSON."""
    user = (
        f"QUESTION:\n{question}\n\n"
        f"TOOL RESULTS (ground truth):\n{json.dumps(tool_results, ensure_ascii=False, default=str)}\n\n"
        f"ANSWER:\n{answer}\n\n"
        'Grade it. Reply with only the JSON {"verdict": ..., "reason": ...}.'
    )
    return [{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": user}]


def parse_verdict(content: str) -> dict[str, Any]:
    """Tolerant parse of the judge reply → {verdict, reason}. Anything we can't read as
    an explicit 'faithful' verdict is treated as UNFAITHFUL (fail safe)."""
    text = (content or "").strip()
    data: dict[str, Any] = {}
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001 - try to find a JSON object embedded in prose
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
            except Exception:  # noqa: BLE001
                data = {}
    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict not in ("faithful", "unfaithful"):
        return {"verdict": "unfaithful", "reason": f"unparseable judge reply: {text[:120]}"}
    return {"verdict": verdict, "reason": str(data.get("reason", "")).strip()[:300]}


def judge_faithfulness(
    question: str,
    answer: str,
    tool_results: list[dict[str, Any]],
    settings: Settings,
    *,
    client: Any | None = None,
) -> dict[str, Any]:
    """Grade one prose answer. Returns {verdict: 'faithful'|'unfaithful', reason}.
    `client` may be injected (tests / offline); otherwise the OpenAI client is built.
    Uses the same model as the chatbot (gpt-5-mini) — deterministic settings."""
    if client is None:
        from openai import OpenAI

        client = wrap_openai_if_enabled(OpenAI(api_key=settings.openai_api_key))

    messages = build_messages(question, answer, tool_results)
    model = settings.openai_model
    # gpt-5*/o* reasoning models require max_completion_tokens and ignore temperature.
    token_arg = (
        {"max_completion_tokens": 2000}
        if model.lower().startswith(("gpt-5", "o1", "o3", "o4"))
        else {"max_tokens": 500, "temperature": 0}
    )
    resp = client.chat.completions.create(model=model, messages=messages, **token_arg)
    return parse_verdict(resp.choices[0].message.content or "")
