"""Write the README's eval badges from the committed eval results.

The badges used to be hardcoded percentages in markdown, which is how a README drifts away
from its own measurements. shields.io renders these JSON files directly, so a badge can only
show what the results say. Run after refreshing an eval; tests/test_badges.py fails if a
committed badge no longer matches its results.

    python scripts/make_badges.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[1] / "eval"
BADGE_DIR = EVAL_DIR / "badges"


def _badge(label: str, accuracy: float) -> dict[str, object]:
    color = "brightgreen" if accuracy >= 0.95 else "green" if accuracy >= 0.9 else "yellow"
    return {"schemaVersion": 1, "label": label, "message": f"{100 * accuracy:.1f}%", "color": color}


def _judge_badge(calibration: str) -> dict[str, object]:
    verdict = re.search(r"\*\*Verdict: ([A-Z ]+)\*\*", calibration)
    examples = re.search(r"\((\d+) examples", calibration)
    if verdict and examples and verdict.group(1) == "TRUSTED":
        return {"schemaVersion": 1, "label": "faithfulness judge", "message": f"calibrated, n={examples.group(1)}", "color": "green"}
    return {"schemaVersion": 1, "label": "faithfulness judge", "message": "not calibrated", "color": "red"}


def build_badges() -> dict[str, dict[str, object]]:
    extraction = json.loads((EVAL_DIR / "metrics.json").read_text(encoding="utf-8"))
    chatbot = json.loads((EVAL_DIR / "chatbot" / "metrics.json").read_text(encoding="utf-8"))
    return {
        "extraction.json": _badge("extraction accuracy", extraction["overall"]["accuracy"]),
        "chatbot-tools.json": _badge("chatbot tool-selection", chatbot["fields"]["tool_selection"]["accuracy"]),
        "judge.json": _judge_badge((EVAL_DIR / "chatbot" / "CALIBRATION.md").read_text(encoding="utf-8")),
    }


def main() -> None:
    BADGE_DIR.mkdir(exist_ok=True)
    for name, badge in build_badges().items():
        (BADGE_DIR / name).write_text(json.dumps(badge, indent=2) + "\n", encoding="utf-8")
        print(f"{name}: {badge['message']}")


if __name__ == "__main__":
    main()
