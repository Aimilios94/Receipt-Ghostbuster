"""A read-only demo refuses every write and every paid call, and still answers reads.

The hosted demo runs with DEMO_READ_ONLY=true over invented data. These tests walk every
route the app registers, so a write route added later is covered without editing this file.
"""
import re

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import get_settings

# CORS reads its allowed origins once, when the app starts, so use one it allows.
ORIGIN = main.settings.cors_origin_list[0]


@pytest.fixture
def client(monkeypatch):
    def with_mode(read_only: bool) -> TestClient:
        monkeypatch.setenv("DEMO_READ_ONLY", "true" if read_only else "false")
        get_settings.cache_clear()
        return TestClient(main.app)

    yield with_mode
    get_settings.cache_clear()


def _concrete(path: str) -> str:
    """Fill path parameters with harmless values; the refusal happens before any route runs."""
    return re.sub(r"\{[^}]+\}", "00000000-0000-0000-0000-000000000000", path)


def _write_routes():
    """Every operation the app serves, from its OpenAPI schema, which lists included routers too."""
    for path, operations in main.app.openapi()["paths"].items():
        for method in operations:
            if method.upper() not in {"GET", "HEAD", "OPTIONS"}:
                yield method.upper(), path


WRITES = sorted(set(_write_routes()))


def test_the_app_has_write_routes_to_guard():
    assert len(WRITES) >= 20
    assert ("POST", "/extract") in WRITES
    assert ("POST", "/chat") in WRITES
    assert ("DELETE", "/expenses/{expense_id}") in WRITES


@pytest.mark.parametrize("method, path", [w for w in WRITES if w not in main.READ_ONLY_ALLOWED])
def test_every_write_is_refused_before_it_runs(client, method, path):
    response = client(True).request(method, _concrete(path), headers={"Origin": ORIGIN})
    assert response.status_code == 403
    assert response.json()["detail"] == main.READ_ONLY_MESSAGE
    # CORS wraps the refusal, so the browser can show the message.
    assert response.headers.get("access-control-allow-origin") == ORIGIN


def test_only_the_insight_refresh_is_allowed():
    assert main.READ_ONLY_ALLOWED == {("POST", "/insights/generate")}
    assert not main.refused_in_read_only("POST", "/insights/generate")
    assert not main.refused_in_read_only("POST", "/insights/generate/")
    assert main.refused_in_read_only("POST", "/insights/some-id")
    assert main.refused_in_read_only("PATCH", "/insights/generate")


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS", "get"])
def test_reads_are_never_refused(method):
    assert not main.refused_in_read_only(method, "/expenses")


def test_reads_still_answer_in_read_only_mode(client):
    response = client(True).get("/health")
    assert response.status_code == 200
    assert response.json()["config"]["read_only"] is True


def test_a_preflight_still_succeeds(client):
    response = client(True).options(
        "/expenses", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"}
    )
    assert response.status_code == 200


def test_writes_reach_their_route_when_the_mode_is_off(client):
    # The route itself answers: 401 where no owner is configured (CI), or 422 for the missing
    # file where one is (a local .env). Either way the guard let it through.
    response = client(False).post("/extract")
    assert response.status_code in {401, 422}
    assert response.json()["detail"] != main.READ_ONLY_MESSAGE
    assert client(False).get("/health").json()["config"]["read_only"] is False
