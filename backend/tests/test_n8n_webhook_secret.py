"""The refund-draft call to n8n carries the shared secret when one is set."""
from app.config import Settings
from app.routers import refunds


class _Resp:
    def raise_for_status(self):
        return None


def _deliver(monkeypatch, secret):
    sent = {}

    def fake_post(url, json, headers, timeout):
        sent.update(url=url, json=json, headers=headers)
        return _Resp()

    action = {"id": "a1", "recipient": "billing@example.com", "subject": "Cancel", "email_draft": "Please cancel."}
    monkeypatch.setattr(refunds.httpx, "post", fake_post)
    monkeypatch.setattr(refunds.repo, "list_refund_actions", lambda user_id: [action])
    monkeypatch.setattr(refunds.repo, "update_refund_action", lambda user_id, action_id, patch: {**action, **patch})
    settings = Settings(_env_file=None, n8n_webhook_url="http://localhost:5678/webhook/refund-draft",
                        n8n_webhook_secret=secret)
    out = refunds.deliver_to_gmail("a1", user_id="u1", settings=settings)
    return sent, out


def test_secret_is_sent_as_a_header(monkeypatch):
    sent, out = _deliver(monkeypatch, "s3cret-value")
    assert sent["headers"] == {"X-RG-Webhook-Secret": "s3cret-value"}
    assert sent["json"] == {"to": "billing@example.com", "subject": "Cancel", "message": "Please cancel."}
    assert out["delivered"] is True


def test_no_secret_sends_no_header(monkeypatch):
    sent, _ = _deliver(monkeypatch, "")
    assert sent["headers"] == {}
