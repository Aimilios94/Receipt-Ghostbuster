"""Guardrail-effectiveness and calibration metrics (services/eval_metrics)."""
from app.services import eval_metrics


def _row(expected, predicted, correct, conf):
    return {"expected_gate": expected, "predicted_gate": predicted,
            "field_correct": correct, "confidence": conf}


def test_false_auto_post_rate_counts_wrong_reads_that_posted():
    rows = [
        _row(None, "auto_post", True, 0.95),    # correct, posted — fine
        _row(None, "auto_post", False, 0.9),    # WRONG but posted — a false auto-post
        _row(None, "review", False, 0.6),       # wrong, caught
    ]
    s = eval_metrics.routing_scores(rows)
    assert s["wrong_reads"] == 2
    assert s["false_auto_posts"] == 1
    assert s["false_auto_post_rate"] == 0.5
    assert s["guardrail_recall_on_wrong"] == 0.5


def test_over_review_rate_counts_correct_reads_held_back():
    rows = [
        _row(None, "auto_post", True, 0.95),
        _row(None, "review", True, 0.7),   # correct but held back — over-review
        _row(None, "review", True, 0.7),   # correct but held back — over-review
    ]
    s = eval_metrics.routing_scores(rows)
    assert s["correct_reads"] == 3
    assert s["over_reviewed"] == 2
    assert s["over_review_rate"] == round(2 / 3, 4)


def test_rates_are_none_when_no_denominator():
    s = eval_metrics.routing_scores([_row(None, "auto_post", True, 0.9)])
    assert s["false_auto_post_rate"] is None   # no wrong reads
    assert s["gate_accuracy"] is None          # no expected_gate labels


def test_gate_accuracy_uses_expected_labels_when_present():
    rows = [
        _row("auto_post", "auto_post", True, 0.95),
        _row("review", "review", False, 0.6),
        _row("auto_post", "review", True, 0.7),   # mismatch
    ]
    s = eval_metrics.routing_scores(rows)
    assert s["n_labelled"] == 3
    assert s["gate_accuracy"] == round(2 / 3, 4)


def test_confusion_matrix_only_counts_labelled():
    rows = [
        _row("auto_post", "auto_post", True, 0.95),
        _row("review", "auto_post", False, 0.9),
        _row(None, "review", True, 0.7),   # no expected label -> excluded
    ]
    m = eval_metrics.confusion_matrix(rows)
    assert m["auto_post"]["auto_post"] == 1
    assert m["review"]["auto_post"] == 1
    assert sum(sum(v.values()) for v in m.values()) == 2  # the unlabelled row is excluded


def test_slice_accuracy_buckets_fields_per_tag():
    rows = [
        {"tags": ["rotated", "multi_rate"], "scored": {"total": True, "date": False}},
        {"tags": ["multi_rate"], "scored": {"total": True, "vat_rate": True}},
        {"tags": ["payment_only"], "scored": {"vendor": True}},
    ]
    s = eval_metrics.slice_accuracy(rows)
    # rotated: 1 receipt, 1/2 fields
    assert s["rotated"] == {"correct": 1, "scored": 2, "n_receipts": 1, "accuracy": 0.5}
    # multi_rate spans two receipts: (1/2) + (2/2) = 3/4 fields
    assert s["multi_rate"]["correct"] == 3 and s["multi_rate"]["scored"] == 4
    assert s["multi_rate"]["n_receipts"] == 2 and s["multi_rate"]["accuracy"] == 0.75
    assert s["payment_only"]["accuracy"] == 1.0
    # sorted by tag name
    assert list(s) == ["multi_rate", "payment_only", "rotated"]


def test_slice_accuracy_empty_when_no_tags():
    rows = [{"tags": [], "scored": {"total": True}}, {"scored": {"date": False}}]
    assert eval_metrics.slice_accuracy(rows) == {}


def test_confidence_calibration_buckets():
    rows = [
        _row(None, "auto_post", True, 0.65),
        _row(None, "auto_post", True, 0.72),
        _row(None, "review", False, 0.85),   # high confidence but wrong
    ]
    cal = eval_metrics.confidence_calibration(rows)
    by_range = {b["range"]: b for b in cal}
    assert by_range["0.6-0.7"]["n"] == 1 and by_range["0.6-0.7"]["accuracy"] == 1.0
    assert by_range["0.7-0.8"]["n"] == 1 and by_range["0.7-0.8"]["accuracy"] == 1.0
    assert by_range["0.8-0.9"]["n"] == 1 and by_range["0.8-0.9"]["accuracy"] == 0.0
