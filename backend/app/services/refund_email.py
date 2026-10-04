"""Draft a cancellation / refund email for a subscription (Phase 2, T14).

The LLM only *writes* the draft text. It never sends anything and never touches
money — the draft is persisted with status='draft' and a human approves it; n8n
later pushes the approved draft into Gmail as a DRAFT (still not sent).

Falls back to a deterministic template when no LLM is configured (provider=mock
or missing key), so the feature is fully testable and demoable offline.
"""
from __future__ import annotations

import json
from typing import Any

from ..config import Settings

ACTION_VERB = {"cancel": "cancel", "refund": "request a refund for"}


def _prompt(subscription: dict[str, Any], action: str) -> str:
    verb = ACTION_VERB.get(action, "cancel")
    return (
        "Write a short, polite, professional email to a company's support team to "
        f"{verb} a recurring subscription. Return ONLY a JSON object (no prose, no "
        'markdown fences) with exactly: {"subject": string, "body": string}.\n\n'
        f"Subscription details:\n"
        f"- Vendor: {subscription.get('vendor')}\n"
        f"- Amount: EUR {subscription.get('amount')} {subscription.get('cadence')}\n"
        f"- Roughly EUR {subscription.get('annual_cost')} per year\n\n"
        "Keep it under 120 words. Be firm but courteous. Ask them to confirm the "
        f"{'cancellation' if action == 'cancel' else 'refund'} in writing. Do not "
        "invent an account number; use a placeholder like [your account email] if "
        "an identifier is needed. Sign off as [Your name]."
    )


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    return json.loads(text)


def _draft_anthropic(subscription: dict[str, Any], action: str, settings: Settings) -> dict[str, str]:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    resp = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=512,
        messages=[{"role": "user", "content": _prompt(subscription, action)}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    payload = _parse_json(text)
    return {"subject": str(payload.get("subject", "")), "body": str(payload.get("body", ""))}


def _draft_template(subscription: dict[str, Any], action: str) -> dict[str, str]:
    """Deterministic fallback — no LLM required."""
    vendor = subscription.get("vendor") or "your service"
    amount = subscription.get("amount")
    cadence = subscription.get("cadence", "monthly")
    if action == "refund":
        subject = f"Refund request for my {vendor} subscription"
        ask = (
            f"I am writing to request a refund for the most recent charge of EUR {amount} "
            f"on my {vendor} subscription, which I did not intend to renew."
        )
    else:
        subject = f"Cancellation of my {vendor} subscription"
        ask = (
            f"I would like to cancel my {vendor} subscription (EUR {amount} {cadence}), "
            "effective immediately, and stop all future charges."
        )
    body = (
        "Hello,\n\n"
        f"{ask}\n\n"
        "My account is registered under [your account email]. Please confirm in writing "
        "once this has been processed, along with the effective date.\n\n"
        "Thank you for your help.\n\n"
        "Kind regards,\n[Your name]"
    )
    return {"subject": subject, "body": body}


def draft_email(subscription: dict[str, Any], action: str, settings: Settings) -> dict[str, str]:
    """Return {subject, body}. Uses the configured LLM, else a safe template."""
    provider = settings.llm_provider.lower()
    try:
        if provider == "anthropic" and settings.anthropic_api_key:
            return _draft_anthropic(subscription, action, settings)
    except Exception:
        # Never fail the feature on an LLM hiccup — fall back to the template.
        pass
    return _draft_template(subscription, action)
