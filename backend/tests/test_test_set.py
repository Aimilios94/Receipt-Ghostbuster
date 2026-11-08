"""The held-out set's rules are enforced in code, and a failed read can't shrink a denominator."""
import datetime
import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "scripts"))

import eval_extraction as ev  # noqa: E402
import prepare_test_set as pts  # noqa: E402

TODAY = datetime.date(2026, 11, 6)
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
    b"\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _row(**values):
    return {"file": "a.png", "vendor": "Shop", "date": "13/03/2026", "total": "8,50", **values}


def _folders(tmp_path, *names):
    receipts, dev, cache = tmp_path / "receipts", tmp_path / "dev", tmp_path / "cache"
    for folder in (receipts, dev, cache):
        folder.mkdir()
    for i, name in enumerate(names):
        (receipts / name).write_bytes(PNG + bytes([i]))
    return receipts, dev, cache


def test_values_are_read_as_a_person_writes_them():
    label, errors, _ = pts.row_to_label(
        _row(vat_amount="0,49", vat_rate="6%", also_accept="viva.com | Example Cafe", tags="rotated, new_store"), TODAY
    )
    assert errors == []
    assert label["date"] == "2026-03-13"
    assert label["total"] == 8.5
    assert label["vat_amount"] == 0.49
    assert label["vat_rate"] == 6.0
    assert label["vendor_alt"] == ["viva.com", "Example Cafe"]
    assert label["tags"] == ["rotated", "new_store"]


@pytest.mark.parametrize("written", ["13/03/2026", "13-03-2026", "13.03.2026", "2026-03-13", "13/03/26"])
def test_dates_are_day_first(written):
    assert pts.row_to_label(_row(date=written), TODAY)[0]["date"] == "2026-03-13"


def test_a_blank_field_is_not_scored():
    label, errors, _ = pts.row_to_label({"file": "a.png", "total": "5"}, TODAY)
    assert errors == []
    assert set(label) == {"file", "total"}


@pytest.mark.parametrize("row", [
    _row(total=""),
    _row(date="13/13/2026"),
    _row(date="07/11/2026"),
    _row(vat_amount="1,00"),
    _row(vat_rate="6"),
    _row(vat_amount="99", vat_rate="6"),
    _row(category="Groceries & Food"),
])
def test_bad_values_are_refused(row):
    assert pts.row_to_label(row, TODAY)[1]


def test_sheet_reads_semicolons_commas_and_windows_encoding(tmp_path):
    semicolon = tmp_path / "s.csv"
    semicolon.write_bytes("sep=;\r\nfile;vendor;total\r\na.png;Minipreço;8,50\r\n".encode("cp1252"))
    assert pts.read_rows(semicolon) == [{"file": "a.png", "vendor": "Minipreço", "total": "8,50"}]
    comma = tmp_path / "c.csv"
    comma.write_text('file,total\na.png,"8,50"\n,\n', encoding="utf-8")
    assert pts.read_rows(comma) == [{"file": "a.png", "total": "8,50"}]


def test_photos_and_rows_must_match(tmp_path):
    receipts, dev, cache = _folders(tmp_path, "a.png", "b.png")
    _, errors, _ = pts.validate([_row(), _row(file="c.png")], receipts, dev, cache, TODAY)
    assert any("c.png: no photo" in e for e in errors)
    assert any("b.png: photo has no row" in e for e in errors)


def test_a_seen_photo_cannot_be_a_test_receipt(tmp_path):
    receipts, dev, cache = _folders(tmp_path, "a.png", "b.png", "c.png")
    (dev / "old.png").write_bytes((receipts / "a.png").read_bytes())
    (cache / "b.openai.gpt-5-mini.models.json").write_text("{}", encoding="utf-8")
    (dev / "c.png").write_bytes(PNG + b"other")
    rows = [_row(), _row(file="b.png"), _row(file="c.png")]
    _, errors, _ = pts.validate(rows, receipts, dev, cache, TODAY)
    assert any("a.png: the same photo is in the development set" in e for e in errors)
    assert any("b.png: the eval has already read" in e for e in errors)
    assert any("c.png: a development receipt already has this file name" in e for e in errors)


def test_a_clean_set_passes_and_a_small_one_is_only_a_note(tmp_path):
    receipts, dev, cache = _folders(tmp_path, "a.png")
    labels, errors, warnings = pts.validate([_row()], receipts, dev, cache, TODAY)
    assert errors == []
    assert labels[0]["file"] == "a.png"
    assert any("10 or more" in w for w in warnings)


def _frozen_set(tmp_path, name="test"):
    test_dir = tmp_path / name
    (test_dir / "receipts").mkdir(parents=True)
    (test_dir / "receipts" / "a.png").write_bytes(PNG)
    labels = [{"file": "a.png", "vendor": "Shop", "total": 1.0}]
    labels_path = test_dir / "labels.json"
    labels_path.write_text(json.dumps(labels), encoding="utf-8")
    manifest = ev.freeze_manifest(labels_path, test_dir / "receipts", labels)
    manifest.update(frozen_on="2026-11-06", corrections=[])
    (test_dir / "freeze.json").write_text(json.dumps(manifest), encoding="utf-8")
    return test_dir


def test_scoring_needs_an_unchanged_frozen_set(tmp_path):
    assert ev.check_frozen(tmp_path) != []
    test_dir = _frozen_set(tmp_path)
    assert ev.check_frozen(test_dir) == []
    (test_dir / "labels.json").write_text("[]", encoding="utf-8")
    assert "labels.json changed after freezing." in ev.check_frozen(test_dir)
    test_dir = _frozen_set(tmp_path / "second")
    (test_dir / "receipts" / "a.png").write_bytes(PNG + b"edited")
    assert "a.png changed after freezing." in ev.check_frozen(test_dir)


def _run_main(monkeypatch, tmp_path, *extra):
    argv = ["eval_extraction.py", "--provider", "mock", *extra,
            "--metrics-out", str(tmp_path / "m.json"), "--results-out", str(tmp_path / "r.md"),
            "--detail-out", str(tmp_path / "d.json")]
    monkeypatch.setattr(sys, "argv", argv)
    return ev.main()


def test_test_set_flag_refuses_an_unfrozen_set_and_a_refresh(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ev, "TEST_DIR", tmp_path / "nothing")
    assert _run_main(monkeypatch, tmp_path, "--test-set") == 2
    assert "isn't frozen" in capsys.readouterr().out
    assert _run_main(monkeypatch, tmp_path, "--test-set", "--refresh") == 2
    assert not (tmp_path / "m.json").exists()


def test_test_set_results_are_labelled_and_show_corrections(monkeypatch, tmp_path):
    test_dir = _frozen_set(tmp_path)
    freeze = json.loads((test_dir / "freeze.json").read_text(encoding="utf-8"))
    freeze["corrections"] = [{"date": "2026-11-07", "reason": "the total was mistyped"}]
    (test_dir / "freeze.json").write_text(json.dumps(freeze), encoding="utf-8")
    monkeypatch.setattr(ev, "TEST_DIR", test_dir)
    read = ev.ExtractionResult(vendor="Shop", total=1.0, confidence=0.9)
    monkeypatch.setattr(ev, "read_receipt", lambda *a, **k: (read, {"read_date": "2026-11-06"}))
    assert _run_main(monkeypatch, tmp_path, "--test-set") == 0
    results = (tmp_path / "r.md").read_text(encoding="utf-8")
    assert "held-out test set" in results
    assert "the total was mistyped" in results
    assert json.loads((tmp_path / "m.json").read_text(encoding="utf-8"))["set"] == "held_out_test"


def test_a_failed_read_and_a_missing_image_are_declared(monkeypatch, tmp_path):
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    (receipts / "good.png").write_bytes(PNG)
    (receipts / "bad.png").write_bytes(PNG)
    labels = [{"file": f, "vendor": "Shop", "total": 1.0} for f in ("good.png", "bad.png", "gone.png")]
    labels_path = tmp_path / "labels.json"
    labels_path.write_text(json.dumps(labels), encoding="utf-8")

    def read(path, *a, **k):
        if path.name == "bad.png":
            raise ValueError("crashed")
        return ev.ExtractionResult(vendor="Shop", total=1.0, confidence=0.9), {"read_date": "2026-11-06"}

    monkeypatch.setattr(ev, "read_receipt", read)
    assert _run_main(monkeypatch, tmp_path, "--labels", str(labels_path), "--receipts", str(receipts)) == 0
    metrics = json.loads((tmp_path / "m.json").read_text(encoding="utf-8"))
    assert metrics["n_labelled"] == 3
    assert metrics["n_errored"] == 1
    assert metrics["n_missing"] == 1
    assert metrics["error_types"] == {"ValueError": 1}
    assert metrics["n_receipts"] == 1
    assert metrics["receipts_fully_correct"] == {"count": 1, "n": 2}
    assert metrics["overall"]["scored"] == 4
    assert metrics["overall"]["correct"] == 2
    assert "Declared gaps" in (tmp_path / "r.md").read_text(encoding="utf-8")


def test_the_test_set_matrix_leaves_the_development_matrix_alone(monkeypatch, tmp_path):
    import eval_models as em

    test_dir = _frozen_set(tmp_path)
    monkeypatch.setattr(ev, "TEST_DIR", test_dir)
    read = ev.ExtractionResult(vendor="Shop", total=1.0, confidence=0.9)
    monkeypatch.setattr(ev, "read_receipt", lambda *a, **k: (read, {"read_date": "2026-11-06", "latency_ms": 5}))
    before = em.MODELS_JSON.read_bytes(), em.MODELS_MD.read_bytes()
    monkeypatch.setattr(sys, "argv", ["eval_models.py", "--models", "mock:mock", "--test-set"])

    assert em.main() == 0

    assert (em.MODELS_JSON.read_bytes(), em.MODELS_MD.read_bytes()) == before
    assert "held out from the development set" in (test_dir / "MODELS.md").read_text(encoding="utf-8")


# ---- A later batch is its own set: frozen, read and published apart from the first ----------
NOV = "test-2026-11"


def _two_sets(monkeypatch, tmp_path):
    """A frozen first set and an eval/ folder where later sets live, both in tmp_path."""
    first = _frozen_set(tmp_path)
    monkeypatch.setattr(ev, "EVAL_DIR", tmp_path)
    monkeypatch.setattr(ev, "TEST_DIR", first)
    return first


def test_a_set_name_picks_a_folder_under_eval_and_nothing_else(monkeypatch, tmp_path):
    monkeypatch.setattr(ev, "EVAL_DIR", tmp_path)
    monkeypatch.setattr(ev, "TEST_DIR", tmp_path / "test")
    assert ev.test_set_dir(None) == ev.test_set_dir("test") == tmp_path / "test"
    assert ev.test_set_dir(NOV) == tmp_path / NOV
    assert ev.set_flag(tmp_path / "test") == "--test-set"
    assert ev.set_flag(tmp_path / NOV) == f"--set {NOV}"
    for bad in ["receipts", "../test-1", "test/../receipts", "Test-2026", "test_2026", ""]:
        with pytest.raises(ValueError):
            ev.test_set_dir(bad)


def test_a_photo_from_another_held_out_set_is_not_new(tmp_path):
    receipts, dev, cache = _folders(tmp_path, "a.png", "b.png")
    first = tmp_path / "test" / "receipts"
    first.mkdir(parents=True)
    (first / "old.png").write_bytes((receipts / "a.png").read_bytes())
    (first / "b.png").write_bytes(PNG + b"other")
    _, errors, _ = pts.validate([_row(), _row(file="b.png")], receipts, dev, cache, TODAY, other_receipts=[first])
    assert any("a.png: the same photo is already in the held-out set as test/old.png" in e for e in errors)
    assert any("b.png: a receipt in the held-out set test already has this file name" in e for e in errors)


def test_a_second_set_freezes_without_touching_the_first(monkeypatch, tmp_path):
    first = _two_sets(monkeypatch, tmp_path)
    first_freeze = (first / "freeze.json").read_bytes()
    dev, cache = tmp_path / "dev", tmp_path / "cache"
    dev.mkdir()
    cache.mkdir()
    monkeypatch.setattr(ev, "RECEIPTS_DIR", dev)
    monkeypatch.setattr(ev, "CACHE_DIR", cache)

    assert pts.main(["init", "--set", NOV]) == 0
    (tmp_path / NOV / "receipts" / "n.png").write_bytes(PNG + b"november")
    (tmp_path / NOV / "true-values.csv").write_text("sep=;\nfile;total\nn.png;8,50\n", encoding="utf-8")
    assert pts.main(["check", "--set", NOV]) == 0
    assert pts.main(["freeze", "--set", NOV]) == 0

    assert (first / "freeze.json").read_bytes() == first_freeze
    assert ev.check_frozen(first) == []
    assert ev.check_frozen(tmp_path / NOV) == []
    frozen = json.loads((tmp_path / NOV / "freeze.json").read_text(encoding="utf-8"))
    assert list(frozen["receipts_sha256"]) == ["n.png"]
    assert pts.main(["freeze", "--set", NOV]) == 1  # a second freeze still needs --correction


def test_scoring_a_named_set_writes_its_own_results(monkeypatch, tmp_path, capsys):
    _two_sets(monkeypatch, tmp_path)
    assert _run_main(monkeypatch, tmp_path, "--set", NOV) == 2
    assert f"prepare_test_set.py freeze --set {NOV}" in capsys.readouterr().out

    nov = _frozen_set(tmp_path, NOV)
    read = ev.ExtractionResult(vendor="Shop", total=1.0, confidence=0.9)
    monkeypatch.setattr(ev, "read_receipt", lambda *a, **k: (read, {"read_date": "2026-12-01"}))
    monkeypatch.setattr(sys, "argv", ["eval_extraction.py", "--provider", "mock", "--set", NOV])
    assert ev.main() == 0
    results = (nov / "RESULTS.md").read_text(encoding="utf-8")
    assert "held-out test set" in results
    assert f"eval_extraction.py --set {NOV}" in results
    assert json.loads((nov / "metrics.json").read_text(encoding="utf-8"))["set"] == "held_out_test"
    assert not (tmp_path / "test" / "RESULTS.md").exists()


def test_the_matrix_for_a_named_set_stays_in_its_folder(monkeypatch, tmp_path):
    import eval_models as em

    first = _two_sets(monkeypatch, tmp_path)
    nov = _frozen_set(tmp_path, NOV)
    read = ev.ExtractionResult(vendor="Shop", total=1.0, confidence=0.9)
    monkeypatch.setattr(ev, "read_receipt", lambda *a, **k: (read, {"read_date": "2026-12-01", "latency_ms": 5}))
    before = em.MODELS_JSON.read_bytes(), em.MODELS_MD.read_bytes()
    monkeypatch.setattr(sys, "argv", ["eval_models.py", "--models", "mock:mock", "--set", NOV])

    assert em.main() == 0

    assert (em.MODELS_JSON.read_bytes(), em.MODELS_MD.read_bytes()) == before
    assert not (first / "models.json").exists()
    row = json.loads((nov / "models.json").read_text(encoding="utf-8"))["models"][0]
    assert row["provenance"]["command"].endswith(f"--set {NOV}")


# ---- VAT per rate: a separate score that can't move the main number --------------------------
LINES = "6%: 10,00 / 0,60 / 10,60 | 13%: 10,00 / 1,30 / 11,30 | 23%: 1,00 / 0,23 / 1,23"
VAT_ROW = {"file": "a.png", "total": "23,13", "vat_amount": "2,13", "vat_rate": "13", "vat_lines": LINES}


def test_vat_lines_are_read_as_a_person_writes_them():
    label, errors, warnings = pts.row_to_label(VAT_ROW, TODAY)
    assert errors == [] and not [w for w in warnings if "vat" in w]
    assert label["vat_lines"][0] == {"rate": 6.0, "net": 10.0, "vat": 0.6, "gross": 10.6}
    assert [line["rate"] for line in label["vat_lines"]] == [6.0, 13.0, 23.0]


@pytest.mark.parametrize("change, expected", [
    ({"vat_lines": "6%: 10,00 / 0,60"}, "should look like"),
    ({"vat_lines": "six: 10,00 / 0,60 / 10,60"}, "should look like"),
    ({"vat_lines": LINES.replace("10,60", "10,70")}, "net + VAT"),
    ({"vat_lines": LINES.replace("23%", "13%")}, "same rate twice"),
    ({"total": "23,50"}, "add up to the receipt's total"),
    ({"vat_amount": "2,50"}, "add up to vat_amount"),
    ({"vat_rate": "6"}, "largest total"),
    ({"vat_amount": "", "vat_rate": ""}, "needs vat_amount and vat_rate"),
])
def test_typos_in_vat_lines_are_refused(change, expected):
    assert any(expected in e for e in pts.row_to_label({**VAT_ROW, **change}, TODAY)[1])


def test_the_main_rate_goes_by_total_not_by_net():
    row = {"file": "a.png", "total": "11,71", "vat_amount": "1,01", "vat_rate": "13",
           "vat_lines": "6%: 5,50 / 0,33 / 5,83 | 13%: 5,20 / 0,68 / 5,88"}
    assert pts.row_to_label(row, TODAY)[1] == []


def test_a_vat_mismatch_with_the_rate_is_only_a_note():
    row = {"file": "a.png", "total": "49", "vat_amount": "9", "vat_rate": "23", "vat_lines": "23%: 40 / 9 / 49"}
    label, errors, warnings = pts.row_to_label(row, TODAY)
    assert errors == []
    assert any("VAT doesn't match the rate" in w for w in warnings)


def _breakdown(*rates):
    return {"rates": [{"rate": r, "net": n, "vat_amount": v, "gross": g} for r, n, v, g in rates]}


TRUE_LINES = [{"rate": 6.0, "net": 10.0, "vat": 0.6, "gross": 10.6}, {"rate": 23.0, "net": 1.0, "vat": 0.23, "gross": 1.23}]


@pytest.mark.parametrize("rates, correct, invented, whole", [
    ([(6.0, 10.0, 0.6, 10.6), (23.0, 1.0, 0.23, 1.23)], 2, [], True),
    ([(6.0, 10.0, 0.6, 10.6), (23.0, 1.0, 0.23, 1.5)], 1, [], False),
    ([(6.0, 10.0, 0.9, 10.6), (23.0, 1.0, 0.23, 1.23)], 1, [], False),
    ([(6.0, 10.5, 0.6, 10.6), (23.0, 1.0, 0.23, 1.23)], 1, [], False),
    ([(6.0, 10.0, 0.6, 10.6)], 1, [], False),
    ([(6.0, 10.0, 0.6, 10.6), (23.0, 1.0, 0.23, 1.23), (13.0, 1.0, 0.13, 1.13)], 2, [13], False),
    ([], 0, [], False),
])
def test_a_rate_needs_its_net_vat_and_total_right(rates, correct, invented, whole):
    score = ev.score_vat_lines(TRUE_LINES, _breakdown(*rates))
    assert (score["correct"], score["extra_rates"], score["all_correct"]) == (correct, invented, whole)


def _read_with_table(*rows, total):
    return ev.ExtractionResult(
        vendor="Shop", total=total, confidence=0.9,
        tax_lines=[{"rate": r, "net": n, "vat": v, "gross": g} for r, n, v, g in rows],
    )


def test_a_perfect_read_scores_full_marks_through_the_shipped_logic():
    """Rounding in the app's own VAT code must not cost a correct read any marks."""
    rows = [(6, 4.72, 0.28, 5.00), (13, 3.54, 0.46, 4.00), (23, 0.81, 0.19, 1.00)]
    fields = ev.receipt_fields.compute(_read_with_table(*rows, total=10.00), ev.CATEGORIES)
    lines = [{"rate": float(r), "net": n, "vat": v, "gross": g} for r, n, v, g in rows]
    assert ev.score_vat_lines(lines, fields["breakdown"])["all_correct"] is True


def _per_rate_run(monkeypatch, tmp_path, label, read):
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    (receipts / "a.png").write_bytes(PNG)
    labels_path = tmp_path / "labels.json"
    labels_path.write_text(json.dumps([label]), encoding="utf-8")
    monkeypatch.setattr(ev, "read_receipt", read)
    assert _run_main(monkeypatch, tmp_path, "--labels", str(labels_path), "--receipts", str(receipts)) == 0
    return json.loads((tmp_path / "m.json").read_text(encoding="utf-8")), (tmp_path / "r.md").read_text(encoding="utf-8")


def test_a_wrong_rate_lowers_its_own_score_and_never_the_main_one(monkeypatch, tmp_path):
    label = {"file": "a.png", "vendor": "Shop", "total": 11.83, "vat_amount": 0.83, "vat_rate": 6, "vat_lines": TRUE_LINES}
    swapped = _read_with_table((6, 10.2, 0.61, 10.81), (23, 0.83, 0.19, 1.02), total=11.83)
    metrics, results = _per_rate_run(monkeypatch, tmp_path, label, lambda *a, **k: (swapped, {"read_date": "2026-11-06"}))
    assert metrics["fields"]["total"]["correct"] == 1
    assert metrics["per_rate_vat"]["correct"] == 0
    assert metrics["per_rate_vat"]["receipts_fully_correct"] == {"count": 0, "n": 1}
    assert "## VAT per rate" in results


def test_a_failed_read_counts_against_the_per_rate_score(monkeypatch, tmp_path):
    label = {"file": "a.png", "total": 11.83, "vat_amount": 0.83, "vat_rate": 6, "vat_lines": TRUE_LINES}

    def crash(*a, **k):
        raise ValueError("crashed")

    receipts = tmp_path / "receipts"
    receipts.mkdir()
    (receipts / "a.png").write_bytes(PNG)
    (receipts / "b.png").write_bytes(PNG)
    labels_path = tmp_path / "labels.json"
    labels_path.write_text(json.dumps([label, {"file": "b.png", "total": 1.0}]), encoding="utf-8")
    good = ev.ExtractionResult(total=1.0, confidence=0.9)

    def read(path, *a, **k):
        if path.name == "a.png":
            crash()
        return good, {"read_date": "2026-11-06"}

    monkeypatch.setattr(ev, "read_receipt", read)
    assert _run_main(monkeypatch, tmp_path, "--labels", str(labels_path), "--receipts", str(receipts)) == 0
    per_rate = json.loads((tmp_path / "m.json").read_text(encoding="utf-8"))["per_rate_vat"]
    assert (per_rate["correct"], per_rate["scored"]) == (0, 2)
    assert per_rate["receipts_fully_correct"] == {"count": 0, "n": 1}


def test_labels_without_rates_produce_no_per_rate_output(monkeypatch, tmp_path):
    """The development set has no per-rate labels, so its results must not change shape."""
    label = {"file": "a.png", "vendor": "Shop", "total": 1.0}
    read = ev.ExtractionResult(vendor="Shop", total=1.0, confidence=0.9)
    metrics, results = _per_rate_run(monkeypatch, tmp_path, label, lambda *a, **k: (read, {"read_date": "2026-11-06"}))
    assert "per_rate_vat" not in metrics
    assert "VAT per rate" not in results


def test_the_matrix_reports_per_rate_only_when_labelled(monkeypatch, tmp_path):
    import eval_models as em

    test_dir = _frozen_set(tmp_path)
    labels = [{"file": "a.png", "vendor": "Shop", "total": 11.83, "vat_amount": 0.83, "vat_rate": 6, "vat_lines": TRUE_LINES}]
    labels_path = test_dir / "labels.json"
    labels_path.write_text(json.dumps(labels), encoding="utf-8")
    manifest = ev.freeze_manifest(labels_path, test_dir / "receipts", labels)
    manifest.update(frozen_on="2026-11-06", corrections=[])
    (test_dir / "freeze.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(ev, "TEST_DIR", test_dir)
    read = _read_with_table((6, 10.0, 0.6, 10.6), (23, 1.0, 0.23, 1.23), total=11.83)
    monkeypatch.setattr(ev, "read_receipt", lambda *a, **k: (read, {"read_date": "2026-11-06", "latency_ms": 5}))
    monkeypatch.setattr(sys, "argv", ["eval_models.py", "--models", "mock:mock", "--test-set"])
    assert em.main() == 0
    assert "## VAT per rate" in (test_dir / "MODELS.md").read_text(encoding="utf-8")
    row = json.loads((test_dir / "models.json").read_text(encoding="utf-8"))["models"][0]
    assert row["per_rate_vat"]["correct"] == 2


def test_the_template_examples_pass_the_sheet_checks():
    rows = pts.read_rows(pts.TEST_DIR / "true-values.template.csv")
    assert list(rows[0]) == pts.COLUMNS
    assert len(rows) == 2
    for row in rows:
        assert pts.row_to_label(row, TODAY)[1] == []
