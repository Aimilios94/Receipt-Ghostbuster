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


def test_scoring_the_same_reads_again_is_not_a_new_run():
    reads = {"run_date": "2026-11-06", "reads_from": "2026-11-06", "reads_to": "2026-11-06"}
    old = _row("openai", "a", correct=9, provenance=reads)
    merged = em.merge_results([old], [_row("openai", "a", correct=9, provenance=reads)])
    assert "history" not in merged[0]


def test_new_reads_or_a_changed_score_do_stay_in_the_history():
    october = {"run_date": "2026-10-22", "reads_from": "2026-10-21", "reads_to": "2026-10-22"}
    fresh = {"run_date": "2026-11-06", "reads_from": "2026-11-06", "reads_to": "2026-11-06"}
    new_reads = em.merge_results([_row("openai", "a", correct=9, provenance=october)],
                                 [_row("openai", "a", correct=9, provenance=fresh)])
    assert new_reads[0]["history"][0]["reads_to"] == "2026-10-22"
    rescored = em.merge_results([_row("openai", "a", correct=8, provenance=october)],
                                [_row("openai", "a", correct=9, provenance=october)])
    assert rescored[0]["history"][0]["correct"] == 8


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
    assert "Earlier result for `c`, scored 2026-10-22" in text
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


def test_both_harnesses_score_the_same_read(monkeypatch, tmp_path):
    """RESULTS.md and the matrix once disagreed because each made its own read of a
    non-deterministic model. One read must now serve both."""
    calls = []
    result = em.ev.ExtractionResult(vendor="Shop", total=1.0, confidence=0.9)

    def fake_extract(image_bytes, name, settings):
        calls.append(name)
        return result, b"oriented", {"latency_ms": 5, "est_cost_usd": 0.01}

    monkeypatch.setattr(em.ev, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(em.ev.extraction, "extract_receipt", fake_extract)
    image = tmp_path / "r.jpg"
    image.write_bytes(b"x")
    settings = em.Settings(_env_file=None, llm_provider="openai", openai_model="m")

    from_matrix, trace = em._extract_with_trace(image, settings, TODAY, use_cache=True)
    from_results = em.ev._extract(image, settings, TODAY, use_cache=True)

    assert calls == ["r.jpg"]
    assert from_results.vendor == from_matrix.vendor == "Shop"
    assert trace["read_date"] == em.ev._read_on(tmp_path / "r.openai.m.models.json")


def test_a_fresh_read_is_dated_when_it_was_saved_not_when_the_run_started(monkeypatch, tmp_path):
    """A run that started on 2026-11-11 and read past midnight dated every read 2026-11-11, so
    scoring the same saved reads later gave a different date range and a duplicate history line."""
    import datetime
    import os

    result = em.ev.ExtractionResult(vendor="Shop", total=1.0, confidence=0.9)
    monkeypatch.setattr(em.ev, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(em.ev.extraction, "extract_receipt",
                        lambda image_bytes, name, settings: (result, b"oriented", {"latency_ms": 5}))
    image = tmp_path / "r.jpg"
    image.write_bytes(b"x")
    settings = em.Settings(_env_file=None, llm_provider="openai", openai_model="m")
    run_started = datetime.date(2020, 1, 1)  # long before the read is actually saved

    _, fresh = em._extract_with_trace(image, settings, run_started, use_cache=False)
    _, saved = em._extract_with_trace(image, settings, run_started, use_cache=True)

    assert fresh["read_date"] != run_started.isoformat()
    assert fresh["read_date"] == saved["read_date"]
    cache = tmp_path / "r.openai.m.models.json"
    assert fresh["read_date"] == datetime.date.fromtimestamp(os.stat(cache).st_mtime).isoformat()
