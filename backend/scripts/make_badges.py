"""Write the README's accuracy badges from the committed eval metrics.

The badges used to be hardcoded percentages in markdown, which is how a README drifts away
from its own measurements. shields.io renders these JSON files directly, so a badge can only
show what metrics.json says. Run after refreshing an eval; tests/test_badges.py fails if a
committed badge no longer matches its metrics file.

    python scripts/make_badges.py
"""
from __future__ import annotations

import json
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[1] / "eval"
BADGE_DIR = EVAL_DIR / "badges"


def _badge(label: str, accuracy: float) -> dict[str, object]:
    color = "brightgreen" if accuracy >= 0.95 else "green" if accuracy >= 0.9 else "yellow"
    return {"schemaVersion": 1, "label": label, "message": f"{100 * accuracy:.1f}%", "color": color}


def build_badges() -> dict[str, dict[str, object]]:
    extraction = json.loads((EVAL_DIR / "metrics.json").read_text(encoding="utf-8"))
    chatbot = json.loads((EVAL_DIR / "chatbot" / "metrics.json").read_text(encoding="utf-8"))
    return {
        "extraction.json": _badge("extraction accuracy", extraction["overall"]["accuracy"]),
        "chatbot-tools.json": _badge("chatbot tool-selection", chatbot["fields"]["tool_selection"]["accuracy"]),
    }


def main() -> None:
    BADGE_DIR.mkdir(exist_ok=True)
    for name, badge in build_badges().items():
        (BADGE_DIR / name).write_text(json.dumps(badge, indent=2) + "\n", encoding="utf-8")
        print(f"{name}: {badge['message']}")


if __name__ == "__main__":
    main()
