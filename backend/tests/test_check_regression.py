"""The accuracy-regression gate (scripts/check_regression.py::check) — pure
comparison of a produced metrics dict against a committed baseline floor."""
import json
import sys
from pathlib import Path

# scripts/ is not a package on the path; add it so we can import the gate module.
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import check_regression as cr  # noqa: E402

EVAL = Path(__file__).resolve().parents[1] / "eval"


def _metrics(overall=0.99, date=0.96, fc_count=25, fc_n=26, n=26):
    return {
        "n_receipts": n,
        "overall": {"accuracy": overall},
        "fields": {
            "vendor": {"accuracy": 1.0},
            "date": {"accuracy": date},
            "total": {"accuracy": 1.0},
            "vat_amount": {"accuracy": 1.0},
            "vat_rate": {"accuracy": 1.0},
            "category": {"accuracy": 1.0},
        },
        "receipts_fully_correct": {"count": fc_count, "n": fc_n},
    }


def _baseline(tol=1.0):
    return {
        "tolerance_pp": tol,
        "n_receipts": 26,
        "overall_accuracy": 0.99,
        "fields": {"vendor": 1.0, "date": 0.96, "total": 1.0,
                   "vat_amount": 1.0, "vat_rate": 1.0, "category": 1.0},
        "receipts_fully_correct": 0.9615,
    }


def test_identical_metrics_pass():
    ok, rows = cr.check(_metrics(), _baseline())
    assert ok is True
    assert all(r["ok"] for r in rows)


def test_improvement_passes():
    # Current ABOVE baseline is never a regression.
    ok, _ = cr.check(_metrics(overall=1.0, date=1.0, fc_count=26), _baseline())
    assert ok is True


def test_field_drop_beyond_tolerance_fails():
    # date 0.96 -> 0.90 is a 6pp drop, well past the 1pp band.
    ok, rows = cr.check(_metrics(date=0.90), _baseline())
    assert ok is False
    failed = [r for r in rows if not r["ok"]]
    assert [r["metric"] for r in failed] == ["field:date"]


def test_drop_within_tolerance_passes():
    # 0.96 -> 0.952 (0.8pp) is inside the 1pp band.
    ok, _ = cr.check(_metrics(date=0.952), _baseline(tol=1.0))
    assert ok is True


def test_drop_just_past_tolerance_fails():
    # 0.96 -> 0.948 (1.2pp) breaches the 1pp band.
    ok, rows = cr.check(_metrics(date=0.948), _baseline(tol=1.0))
    assert ok is False


def test_overall_regression_fails():
    ok, rows = cr.check(_metrics(overall=0.95), _baseline())
    assert ok is False
    assert any(r["metric"] == "overall" and not r["ok"] for r in rows)


def test_missing_field_counts_as_regression():
    m = _metrics()
    m["fields"].pop("date")  # a field the baseline tracks is gone entirely
    ok, rows = cr.check(m, _baseline())
    assert ok is False
    assert any(r["metric"] == "field:date" and not r["ok"] for r in rows)


def test_null_field_accuracy_counts_as_regression():
    m = _metrics()
    m["fields"]["date"] = {"accuracy": None}  # scored=0 -> null
    ok, rows = cr.check(m, _baseline())
    assert ok is False


def test_receipts_fully_correct_regression_fails():
    ok, rows = cr.check(_metrics(fc_count=20), _baseline())  # 20/26 = 77% vs 96% floor
    assert ok is False
    assert any(r["metric"] == "receipts_fully_correct" and not r["ok"] for r in rows)


def test_committed_baselines_are_valid_json_and_shaped():
    for name in ("baseline.json", "baseline.mock.json"):
        data = json.loads((EVAL / name).read_text(encoding="utf-8"))
        assert "overall_accuracy" in data and "fields" in data and "tolerance_pp" in data
        assert 0.0 <= data["overall_accuracy"] <= 1.0


def test_committed_metrics_passes_committed_baseline():
    # The shipped metrics.json must satisfy its own committed floor.
    metrics = json.loads((EVAL / "metrics.json").read_text(encoding="utf-8"))
    baseline = json.loads((EVAL / "baseline.json").read_text(encoding="utf-8"))
    ok, _ = cr.check(metrics, baseline)
    assert ok is True
