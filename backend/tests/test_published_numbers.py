"""The figures people read must match the results they came from. Generated pages must match
their data, and the README, typed by hand, must match both, so a stale number fails CI."""
import json
import re
import sys
from pathlib import Path

import pytest

from app import __version__

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
EVAL = BACKEND / "eval"
sys.path.insert(0, str(BACKEND / "scripts"))

import eval_models as em  # noqa: E402


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


README = (ROOT / "README.md").read_text(encoding="utf-8")
DEV = _json(EVAL / "models.json")
TEST = _json(EVAL / "test" / "models.json")
METRICS = _json(EVAL / "metrics.json")
TEST_METRICS = _json(EVAL / "test" / "metrics.json")
CHAT = _json(EVAL / "chatbot" / "metrics.json")
TEST_ROWS = {r["model"]: r for r in TEST["models"]}
IN_USE = next(r for r in DEV["models"] if r["model"] == METRICS["model"])
LOCAL = next(r for r in DEV["models"] if r["provider"] == "ollama")


def _pct(value):
    return f"{100 * value:.1f}%"


def _seconds(ms):
    return f"{ms / 1000:.1f}s"


def _fraction(score):
    return f"{score['correct']}/{score['scored']}"


def _readme_cells(model):
    rows = [line for line in README.splitlines() if line.startswith(f"| `{model}`")]
    assert len(rows) == 1, f"{model}: expected one row in the README's matrix, found {len(rows)}"
    return [cell.strip() for cell in rows[0].strip().strip("|").split("|")]


@pytest.mark.parametrize("row", DEV["models"], ids=lambda r: r["model"])
def test_a_readme_matrix_row_matches_the_results(row):
    cells = _readme_cells(row["model"])
    held_out = TEST_ROWS.get(row["model"])
    partial = f" (n={row['n_receipts']})" if row["n_receipts"] != DEV["n_receipts"] else ""
    cost = row["cost_usd"]["avg_per_read"]
    assert cells[1:] == [
        _pct(row["overall"]["accuracy"]) + partial,
        _pct(held_out["overall"]["accuracy"]) if held_out else "not run",
        _fraction(held_out["per_rate_vat"]) if held_out else "not run",
        _seconds(row["latency_ms"]["p50"]),
        f"${cost:.4f}" if cost else "$0",
    ]


def test_the_readme_headlines_match_the_metrics():
    assert f"**{_pct(METRICS['overall']['accuracy'])} field accuracy**" in README
    assert f"({_fraction(METRICS['overall'])} fields, `{METRICS['model']}`" in README
    assert f"**{_pct(TEST_METRICS['overall']['accuracy'])} on {TEST_METRICS['n_receipts']} new receipts" in README
    assert f"({_fraction(TEST_METRICS['overall'])} fields" in README
    assert f"all {TEST_METRICS['per_rate_vat']['scored']} VAT rates" in README


def test_the_two_reports_agree_on_the_model_in_use():
    assert (IN_USE["overall"]["correct"], IN_USE["overall"]["scored"]) == (
        METRICS["overall"]["correct"], METRICS["overall"]["scored"]
    )
    held_out = TEST_ROWS[METRICS["model"]]
    assert (held_out["overall"]["correct"], held_out["overall"]["scored"]) == (
        TEST_METRICS["overall"]["correct"], TEST_METRICS["overall"]["scored"]
    )


def test_the_readme_gate_section_matches_the_metrics():
    for metrics in (METRICS, TEST_METRICS):
        g = metrics["guardrails"]
        assert f"{round(100 * g['over_review_rate'])}% of correct reads ({g['over_reviewed']}/{g['correct_reads']})" in README


def test_the_readme_calibration_figures_match_the_metrics():
    bins = {b["range"]: b for b in METRICS["calibration"]}
    low, high = bins["0.7-0.8"], bins["0.8-0.9"]
    assert f"reads at 0.7–0.8 were {round(100 * low['accuracy'])}% correct (n={low['n']})" in README
    assert f"reads at 0.8–0.9 were {round(100 * high['accuracy'])}% (n={high['n']})" in README


def test_the_readme_ask_figures_match_the_metrics():
    f = CHAT["fields"]
    assert (f"Tool choice {_fraction(f['tool_selection'])}, answers {_fraction(f['answer_correctness'])}, "
            f"refusals {_fraction(f['refusal'])}") in README
    assert f"{_fraction(f['faithfulness'])} faithful" in README


def test_the_local_models_range_covers_all_its_runs():
    scores = [LOCAL["overall"]["accuracy"]] + [h["accuracy"] for h in LOCAL["history"]]
    quoted = re.findall(r"\d+\.\d–\d+\.\d%", README)
    assert quoted, "the README should quote the local model's range"
    assert set(quoted) == {f"{100 * min(scores):.1f}–{100 * max(scores):.1f}%"}


def test_the_speed_quoted_in_the_docs_matches_the_results():
    p50, p95 = _seconds(IN_USE["latency_ms"]["p50"]), _seconds(IN_USE["latency_ms"]["p95"])
    assert f"read takes {p50} at p50" in README
    statement = (ROOT / "problem-statement.md").read_text(encoding="utf-8")
    assert f"read takes {p50} at p50 and {p95} at p95" in statement


def test_a_corrected_figure_stays_out_of_the_current_docs():
    for text in (README, json.dumps(DEV, ensure_ascii=False), (BACKEND / ".env.example").read_text(encoding="utf-8")):
        assert "38.5" not in text and "38x" not in text


@pytest.mark.parametrize("doc, page", [(DEV, EVAL / "MODELS.md"), (TEST, EVAL / "test" / "MODELS.md")],
                         ids=["development", "held-out"])
def test_a_model_page_is_exactly_what_its_data_renders(doc, page, tmp_path):
    rendered = tmp_path / "MODELS.md"
    em._write_models_md(doc, path=rendered)
    assert rendered.read_text(encoding="utf-8").splitlines() == page.read_text(encoding="utf-8").splitlines()


def test_a_history_never_lists_the_same_reads_twice():
    for row in DEV["models"] + TEST["models"]:
        seen = set()
        for h in row.get("history", []):
            key = (h.get("reads_from") or h.get("run_date"), h.get("reads_to"), h["correct"], h["scored"])
            assert key not in seen, f"{row['model']}: {key} appears twice"
            seen.add(key)
        current = row["provenance"]
        assert (current.get("reads_from"), current.get("reads_to"),
                row["overall"]["correct"], row["overall"]["scored"]) not in seen


def test_each_held_out_row_says_how_to_reproduce_it():
    for row in TEST["models"]:
        assert row["provenance"]["command"].endswith("--test-set")


def test_the_changelog_leads_with_the_current_version():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    first = next(line for line in changelog.splitlines() if line.startswith("## ["))
    assert first.startswith(f"## [{__version__}]")


def test_the_readme_states_the_real_test_count(request):
    config = request.config
    every_file = {Path(str(item.fspath)).name for item in request.session.items} == {
        p.name for p in Path(__file__).parent.glob("test_*.py")
    }
    if not every_file or config.getoption("keyword") or config.getoption("markexpr"):
        pytest.skip("only a full run knows the count")
    assert f"CI runs {request.session.testscollected} backend tests" in README
