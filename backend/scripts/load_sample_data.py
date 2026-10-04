"""Load the demo dataset into a RUNNING backend, then reconcile and print a close.

Usage (with the API running on :8000 and schema applied):
    python scripts/load_sample_data.py

Calls the API with no auth header, so it uses DEV_USER_ID (dev mode). This is the
one-command demo seeder referenced in the README.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
SAMPLES = REPO / "sample-data"
API = "http://localhost:8000"


def main() -> int:
    client = httpx.Client(base_url=API, timeout=60)

    # 1) Manual + cash expenses
    expenses = json.loads((SAMPLES / "sample_expenses.json").read_text(encoding="utf-8"))
    posted = 0
    for e in expenses:
        r = client.post("/expenses", json=e)
        r.raise_for_status()
        posted += 1
    print(f"Posted {posted} expenses (card + cash).")

    # 2) Bank CSV import
    csv_path = SAMPLES / "bank_september_2026.csv"
    with csv_path.open("rb") as fh:
        r = client.post(
            "/bank/import",
            files={"file": (csv_path.name, fh, "text/csv")},
        )
    r.raise_for_status()
    print(f"Imported bank rows: {r.json()['imported']}")

    # 3) Reconcile
    r = client.post("/reconcile")
    r.raise_for_status()
    rec = r.json()
    print(
        f"Reconciled: matched={rec['matched']} "
        f"unmatched_expenses={rec['unmatched_expenses']} "
        f"unmatched_bank={rec['unmatched_bank']} cash_skipped={rec['cash_skipped']}"
    )

    # 4) Exceptions
    r = client.get("/exceptions")
    r.raise_for_status()
    print("Exceptions:", json.dumps(r.json()["counts"], indent=2))

    # 5) Monthly close
    r = client.get("/close", params={"month": "2026-09"})
    r.raise_for_status()
    print("September close:", json.dumps(r.json(), indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except httpx.HTTPStatusError as exc:
        print(f"HTTP {exc.response.status_code}: {exc.response.text[:400]}")
        sys.exit(1)
    except httpx.ConnectError:
        print("Could not reach the API at http://localhost:8000 — is uvicorn running?")
        sys.exit(1)
