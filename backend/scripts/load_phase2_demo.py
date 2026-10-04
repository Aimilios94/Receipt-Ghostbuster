"""Load the Phase 2 (Refund Hunter) demo data into a RUNNING backend.

Usage (API on :8000, schema applied, Phase 1 sample already loaded):
    python scripts/load_phase2_demo.py

Imports several months of recurring bank charges (Netflix, Spotify, Adobe,
Cosmote, Gym Plus) so subscription detection has real recurrence to find, then
runs detection and prints what it detected.

NOTE: this adds older (Jun–Aug) bank lines to bank_transactions. They are real
unmatched bank charges, so the all-time reconciliation exceptions list will grow
accordingly — the pristine September-only view is Phase 1's demo, this is Phase 2's.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parent.parent
SAMPLES = BACKEND.parent / "sample-data"
API = "http://localhost:8000"


def main() -> int:
    client = httpx.Client(base_url=API, timeout=60)

    csv_path = SAMPLES / "bank_recurring_history.csv"
    with csv_path.open("rb") as fh:
        r = client.post("/bank/import", files={"file": (csv_path.name, fh, "text/csv")})
    r.raise_for_status()
    print(f"Imported recurring bank history: {r.json()['imported']} rows.")

    r = client.post("/subscriptions/detect")
    r.raise_for_status()
    data = r.json()
    print(f"\nDetected {data['detected']} subscriptions:")
    for s in data["subscriptions"]:
        flag = "  [stale]" if s.get("stale") else ""
        print(
            f"  {s['vendor']:<22} {s['cadence']:<9} "
            f"EUR {s['amount']:>7.2f} -> EUR {s['annual_cost']:>8.2f}/yr"
            f"  (seen {s['occurrences']}x){flag}"
        )
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
