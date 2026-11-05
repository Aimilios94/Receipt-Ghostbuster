"""The model matrix must survive a single-model re-measure and declare failed reads."""
import datetime
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "scripts"))

import eval_models as em  # noqa: E402

TODAY = datetime.date(2026, 11, 5)


def _row(provider, model, correct=9, scored=10, **extra):
    fields = {f: {"accuracy": 1.0, "correct": 1, "scored": 1} for f in em.ev.FIELDS}
    return {
        "provider": provider, "model": model, "n_receipts": 2, "n_labelled": 2,
        "fields": fields,
        "overall": {"accuracy": correct / scored, "correct": correct, "scored": scored},
        "receipts_fully_correct": {"count": 1, "n": 2},
        "latency_ms": {"p50": 1000, "p95": 2000, "avg": 1500},
        "cost_usd": {"total": 0.02, "avg_per_read": 0.01},
        "fell_back": 0,
        "guardrails": {"false_auto_posts": 0, "false_auto_post_rate": 0.0, "over_review_rate": 0.5},
        "slices": {},
        **extra,
    }


def test_single_model_run_keeps_every_other_row_and_its_order():
    a, b, c = _row("openai", "a"), _row("openai", "b"), _row("ollama", "c")
    merged = em.merge_results([a, b, c], [_row("openai", "b", correct=5)])
    assert [r["model"] for r in merged] == ["a", "b", "c"]
    assert merged[0] is a and merged[2] is c
    assert merged[1]["overall"]["correct"] == 5


def test_replaced_row_moves_to_history():
    old = _row("ollama", "c", correct=8, provenance={"run_date": "2026-10-22"}, n_errored=1,
               history=[{"run_date": "2026-10-01", "accuracy": 0.5, "correct": 5, "scored": 10,
                         "n_receipts": 2}])
    merged = em.merge_results([old], [_row("ollama", "c", correct=9)])
    assert [h["run_date"] for h in merged[0]["history"]] == ["2026-10-01", "2026-10-22"]
    assert merged[0]["history"][-1]["correct"] == 8
    assert merged[0]["history"][-1]["n_errored"] == 1


def test_new_model_is_appended():
    merged = em.merge_results([_row("openai", "a")], [_row("openai", "z")])
    assert [r["model"] for r in merged] == ["a", "z"]


def test_replace_all_starts_a_new_matrix_but_keeps_the_prose():
    existing = {"models": [_row("openai", "a")], "notes": ["n"], "footnotes": ["f"]}
    doc = em.build_doc([_row("openai", "z")], existing, TODAY, replace_all=True)
    assert [r["model"] for r in doc["models"]] == ["z"]
    assert doc["notes"] == ["n"] and doc["footnotes"] == ["f"]


def test_report_declares_errors_gaps_and_history(tmp_path):
    errored = _row("ollama", "c", n_errored=1, error_types={"ValidationError": 1},
                   history=[{"run_date": "2026-10-22", "accuracy": 0.9, "correct": 9, "scored": 10,
                             "n_receipts": 2}])
    doc = em.build_doc([errored], {"notes": ["a kept note"], "footnotes": ["a kept footnote"]},
                       TODAY, replace_all=False)
    out = tmp_path / "MODELS.md"
    em._write_models_md(doc, path=out)
    text = out.read_text(encoding="utf-8")
    assert "ValidationError ×1" in text and "count as misses" in text
    assert "MEASURED, partial" in text
    assert "Earlier run of `c` on 2026-10-22" in text
    assert "a kept note" in text and "a kept footnote" in text
    assert "NO_DATA (not recorded)" in text


def test_failed_read_is_declared_and_counted_not_dropped(monkeypatch, tmp_path):
    (tmp_path / "ok.jpg").write_bytes(b"x")
    (tmp_path / "bad.jpg").write_bytes(b"x")
    labels = [
        {"file": "ok.jpg", "total": 12.30, "tags": ["t"]},
        {"file": "bad.jpg", "total": 9.99, "tags": ["t"]},
        {"file": "gone.jpg", "total": 1.00},
    ]
    result = em.ExtractionResult(vendor="Shop", total=12.30, confidence=0.9)

    def read(path, settings, today, *, use_cache):
        if path.name == "bad.jpg":
            raise ValueError("boom")
        return result, {"latency_ms": 1000, "est_cost_usd": 0.0, "read_date": "2026-11-03"}

    monkeypatch.setattr(em, "_extract_with_trace", read)
    monkeypatch.setattr(em, "_git_commit", lambda: "abc1234")
    row = em._run_model("mock", "mock", labels, tmp_path, TODAY, use_cache=True)

    assert row["n_receipts"] == 1 and row["n_errored"] == 1 and row["n_missing"] == 1
    assert row["n_labelled"] == 3
    assert row["error_types"] == {"ValueError": 1}
    assert row["fields"]["total"]["correct"] == 1 and row["fields"]["total"]["scored"] == 2
    assert row["receipts_fully_correct"] == {"count": 1, "n": 2}
    assert row["slices"]["t"]["n_receipts"] == 2
    assert row["provenance"]["reads_from"] == "2026-11-03"
    assert row["provenance"]["commit"] == "abc1234"


def test_limit_run_writes_nothing(monkeypatch, tmp_path):
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps([{"file": "ok.jpg", "total": 12.30}]), encoding="utf-8")
    (tmp_path / "ok.jpg").write_bytes(b"x")
    md, js = tmp_path / "MODELS.md", tmp_path / "models.json"
    monkeypatch.setattr(em, "MODELS_MD", md)
    monkeypatch.setattr(em, "MODELS_JSON", js)
    monkeypatch.setattr(em, "_git_commit", lambda: "abc1234")
    monkeypatch.setattr(em, "_extract_with_trace", lambda *a, **k: (
        em.ExtractionResult(vendor="Shop", total=12.30, confidence=0.9),
        {"latency_ms": 1, "est_cost_usd": 0.0, "read_date": "2026-11-05"},
    ))
    monkeypatch.setattr(sys, "argv", ["eval_models.py", "--models", "mock:mock", "--limit", "1",
                                      "--labels", str(labels), "--receipts", str(tmp_path)])
    assert em.main() == 0
    assert not md.exists() and not js.exists()
