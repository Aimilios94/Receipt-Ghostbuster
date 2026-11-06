"""A committed README badge must show what its metrics file says."""
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "scripts"))

import make_badges  # noqa: E402


def test_committed_badges_match_the_metrics():
    for name, expected in make_badges.build_badges().items():
        committed = json.loads((make_badges.BADGE_DIR / name).read_text(encoding="utf-8"))
        assert committed == expected, f"{name} is stale: run scripts/make_badges.py"


def test_badge_colour_follows_the_score():
    assert make_badges._badge("x", 0.993)["message"] == "99.3%"
    assert make_badges._badge("x", 0.993)["color"] == "brightgreen"
    assert make_badges._badge("x", 0.92)["color"] == "green"
    assert make_badges._badge("x", 0.8)["color"] == "yellow"
