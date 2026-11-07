"""Turn hand-written true values into the frozen held-out test set.

The test set answers "did you overfit?", so its rules are enforced here rather than left to
memory: new receipts only, true values written before any model reads them, and no change
afterwards without a recorded reason. See backend/eval/test/README.md.

    python scripts/prepare_test_set.py init     # add a row per photo to true-values.csv
    python scripts/prepare_test_set.py check    # report problems, change nothing
    python scripts/prepare_test_set.py freeze   # write labels.json + freeze.json
    python scripts/prepare_test_set.py freeze --correction "why this label changed"
"""
from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import io
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_extraction as ev  # noqa: E402

from app.models import _to_number  # noqa: E402
from app.services import extraction  # noqa: E402

COLUMNS = ["file", "vendor", "also_accept", "date", "total", "vat_amount", "vat_rate", "vat_lines",
           "category", "tags", "note"]
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
USUAL_VAT_RATES = {0, 6, 13, 23}
SUGGESTED_MINIMUM = 10
MONEY_TOLERANCE = 0.01
TEST_DIR = ev.TEST_DIR
VALUES_CSV = TEST_DIR / "true-values.csv"


def read_rows(path: Path) -> list[dict[str, str]]:
    """Read the sheet however a spreadsheet saved it: comma or semicolon, UTF-8 or Windows."""
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    lines = text.splitlines()
    if lines and lines[0].lower().startswith("sep="):
        lines = lines[1:]
    if not lines:
        return []
    delimiter = max(";,\t", key=lines[0].count)
    rows = csv.DictReader(io.StringIO("\n".join(lines)), delimiter=delimiter)
    cleaned = [{(k or "").strip().lower(): (v or "").strip() for k, v in row.items() if k} for row in rows]
    return [row for row in cleaned if any(row.values())]


def _parse_date(value: str) -> datetime.date | None:
    """Day-first, as printed on Portuguese receipts, or ISO."""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        fmt = "%Y-%m-%d"
    else:
        value = re.sub(r"[-.]", "/", value)
        fmt = "%d/%m/%Y" if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", value) else "%d/%m/%y"
    try:
        return datetime.datetime.strptime(value, fmt).date()
    except ValueError:
        return None


def _parse_number(value: str) -> float | None:
    number = _to_number(value)
    return float(number) if isinstance(number, (int, float)) else None


def parse_vat_lines(text: str) -> tuple[list[dict[str, float]], list[str]]:
    """Read '6%: 5,00 / 0,30 / 5,30 | 23%: 1,00 / 0,23 / 1,23' (rate: net / VAT / total)."""
    lines: list[dict[str, float]] = []
    errors: list[str] = []
    for part in text.split("|"):
        rate_text, colon, figures = part.partition(":")
        values = [_parse_number(v) for v in figures.split("/")] if colon else []
        rate = _parse_number(rate_text.replace("%", ""))
        if rate is None or len(values) != 3 or None in values:
            errors.append(f"vat_lines '{part.strip()}' should look like 6%: 5,00 / 0,30 / 5,30")
            continue
        lines.append({"rate": rate, "net": values[0], "vat": values[1], "gross": values[2]})
    return lines, errors


def check_vat_lines(lines: list[dict[str, float]], label: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Catch typos: the lines must add up, and agree with the receipt's total, VAT and main rate."""
    errors: list[str] = []
    warnings: list[str] = []
    if "vat_amount" not in label or "vat_rate" not in label:
        return ["vat_lines needs vat_amount and vat_rate too"], warnings
    rates = [line["rate"] for line in lines]
    if len(set(rates)) != len(rates):
        errors.append("vat_lines lists the same rate twice")
    for line in lines:
        name = f"{line['rate']:g}%"
        if abs(round(line["net"] + line["vat"], 2) - line["gross"]) > MONEY_TOLERANCE:
            errors.append(f"vat_lines {name}: net + VAT doesn't equal its total")
        if abs(round(line["net"] * line["rate"] / 100, 2) - line["vat"]) > ev.VAT_TOL:
            warnings.append(f"vat_lines {name}: VAT doesn't match the rate on the net: check it's what's printed")
        if line["rate"] not in USUAL_VAT_RATES:
            warnings.append(f"vat_lines {name} isn't 0, 6, 13 or 23: check it's what's printed")
    if "total" in label and abs(round(sum(l["gross"] for l in lines), 2) - label["total"]) > MONEY_TOLERANCE:
        errors.append("vat_lines totals don't add up to the receipt's total")
    if abs(round(sum(l["vat"] for l in lines), 2) - label["vat_amount"]) > MONEY_TOLERANCE:
        errors.append("vat_lines VAT doesn't add up to vat_amount")
    if lines and max(lines, key=lambda l: l["gross"])["rate"] != label["vat_rate"]:
        errors.append("vat_rate must be the rate with the largest total in vat_lines")
    return errors, warnings


def row_to_label(row: dict[str, str], today: datetime.date) -> tuple[dict[str, Any], list[str], list[str]]:
    """One sheet row as a label, plus its errors and warnings. A blank field isn't scored."""
    label: dict[str, Any] = {"file": row.get("file", "")}
    errors: list[str] = []
    warnings: list[str] = []

    if row.get("vendor"):
        label["vendor"] = row["vendor"]
    else:
        warnings.append("no vendor, so vendor won't be scored")
    if row.get("also_accept"):
        label["vendor_alt"] = [v.strip() for v in row["also_accept"].split("|") if v.strip()]

    if row.get("date"):
        date = _parse_date(row["date"])
        if date is None:
            errors.append(f"date '{row['date']}' isn't a date (use 13/03/2026)")
        elif date > today:
            errors.append(f"date {date.isoformat()} is in the future")
        else:
            label["date"] = date.isoformat()
    else:
        warnings.append("no date, so date won't be scored")

    total = _parse_number(row.get("total", ""))
    if total is None or total <= 0:
        errors.append(f"total '{row.get('total', '')}' must be the amount paid, like 8,50")
    else:
        label["total"] = total

    has_amount, has_rate = bool(row.get("vat_amount")), bool(row.get("vat_rate"))
    if has_amount != has_rate:
        errors.append("give both vat_amount and vat_rate, or leave both blank if no VAT is printed")
    if has_amount:
        amount = _parse_number(row["vat_amount"])
        if amount is None or amount < 0:
            errors.append(f"vat_amount '{row['vat_amount']}' isn't a number")
        else:
            label["vat_amount"] = amount
            if total is not None and amount > total:
                errors.append("vat_amount is bigger than the total")
    if has_rate:
        rate = _parse_number(row["vat_rate"].replace("%", ""))
        if rate is None:
            errors.append(f"vat_rate '{row['vat_rate']}' isn't a number")
        else:
            label["vat_rate"] = rate
            if rate not in USUAL_VAT_RATES:
                warnings.append(f"vat_rate {rate:g} isn't 0, 6, 13 or 23: check it's what's printed")
    if row.get("vat_lines"):
        lines, line_errors = parse_vat_lines(row["vat_lines"])
        errors += line_errors
        if not line_errors:
            more_errors, more_warnings = check_vat_lines(lines, label)
            errors += more_errors
            warnings += more_warnings
            label["vat_lines"] = lines

    if row.get("category"):
        if row["category"] in ev.CATEGORIES:
            label["category"] = row["category"]
        else:
            errors.append(f"category '{row['category']}' isn't one of: {', '.join(sorted(ev.CATEGORIES))}")
    if row.get("tags"):
        label["tags"] = [t.strip() for t in re.split(r"[|,]", row["tags"]) if t.strip()]
    return label, errors, warnings


def _photos(receipts_dir: Path) -> list[Path]:
    if not receipts_dir.exists():
        return []
    return sorted(p for p in receipts_dir.iterdir() if p.is_file())


def validate(
    rows: list[dict[str, str]], receipts_dir: Path, dev_dir: Path, cache_dir: Path,
    today: datetime.date, *, after_read: bool = False,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Check the sheet against the photos and the eval's history. Returns labels, errors, warnings."""
    errors: list[str] = []
    warnings: list[str] = []
    labels: list[dict[str, Any]] = []
    photos = {p.name: p for p in _photos(receipts_dir)}
    seen: set[str] = set()

    for number, row in enumerate(rows, start=1):
        name = row.get("file", "")
        where = name or f"row {number}"
        if not name:
            errors.append(f"{where}: no file name")
            continue
        if name in seen:
            errors.append(f"{where}: listed twice")
            continue
        seen.add(name)
        if name not in photos:
            errors.append(f"{where}: no photo with this name in {receipts_dir.name}/")
        label, row_errors, row_warnings = row_to_label(row, today)
        errors += [f"{where}: {e}" for e in row_errors]
        warnings += [f"{where}: {w}" for w in row_warnings]
        labels.append(label)

    for name in sorted(set(photos) - seen):
        errors.append(f"{name}: photo has no row in the sheet")

    dev_hashes = {ev.sha256_of(p): p.name for p in _photos(dev_dir)}
    by_hash: dict[str, str] = {}
    for name, path in photos.items():
        if path.suffix.lower() not in IMAGE_SUFFIXES or not extraction.is_readable_image(path.read_bytes()):
            errors.append(f"{name}: not a readable JPG, PNG or WebP photo")
            continue
        digest = ev.sha256_of(path)
        if digest in dev_hashes:
            errors.append(f"{name}: the same photo is in the development set as {dev_hashes[digest]}")
        if digest in by_hash:
            errors.append(f"{name}: the same photo as {by_hash[digest]}")
        by_hash[digest] = name
        if (dev_dir / name).exists():
            errors.append(f"{name}: a development receipt already has this file name")
        if not after_read and any(cache_dir.glob(f"{path.stem}.*")):
            errors.append(f"{name}: the eval has already read this photo, so it isn't unseen")

    if len(labels) < SUGGESTED_MINIMUM:
        warnings.append(f"{len(labels)} receipts: {SUGGESTED_MINIMUM} or more was the plan")
    return labels, errors, warnings


def _report(errors: list[str], warnings: list[str]) -> None:
    for w in warnings:
        print(f"  note     {w}")
    for e in errors:
        print(f"  PROBLEM  {e}")


def cmd_init(args: argparse.Namespace) -> int:
    """Add a blank row for each photo that doesn't have one. Existing rows are kept."""
    TEST_DIR.mkdir(exist_ok=True)
    (TEST_DIR / "receipts").mkdir(exist_ok=True)
    rows = read_rows(VALUES_CSV) if VALUES_CSV.exists() else []
    known = {row.get("file") for row in rows}
    new = [p.name for p in _photos(TEST_DIR / "receipts") if p.name not in known]
    rows += [{"file": name} for name in new]
    with VALUES_CSV.open("w", encoding="utf-8", newline="") as handle:
        handle.write("sep=;\r\n")
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"{VALUES_CSV.name}: {len(rows)} rows, {len(new)} added.")
    return 0


def _load(args: argparse.Namespace, *, after_read: bool = False):
    if not VALUES_CSV.exists():
        print(f"No {VALUES_CSV.name} yet. Run: python scripts/prepare_test_set.py init")
        return None
    return validate(read_rows(VALUES_CSV), TEST_DIR / "receipts", ev.RECEIPTS_DIR, ev.CACHE_DIR,
                    datetime.date.today(), after_read=after_read)


def cmd_check(args: argparse.Namespace) -> int:
    loaded = _load(args)
    if loaded is None:
        return 2
    labels, errors, warnings = loaded
    _report(errors, warnings)
    print(f"{len(labels)} receipts, {len(errors)} problems, {len(warnings)} notes.")
    return 1 if errors else 0


def cmd_freeze(args: argparse.Namespace) -> int:
    freeze_path = TEST_DIR / "freeze.json"
    previous = json.loads(freeze_path.read_text(encoding="utf-8")) if freeze_path.exists() else None
    loaded = _load(args, after_read=bool(args.correction))
    if loaded is None:
        return 2
    labels, errors, warnings = loaded
    _report(errors, warnings)
    if errors:
        print(f"Not frozen: {len(errors)} problems.")
        return 1
    if previous and not args.correction:
        print("Already frozen. A later change needs --correction with the reason, which is published.")
        return 1

    labels_path = TEST_DIR / "labels.json"
    labels_path.write_text(json.dumps(labels, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest = ev.freeze_manifest(labels_path, TEST_DIR / "receipts", labels)
    manifest["frozen_on"] = (previous or {}).get("frozen_on") or datetime.date.today().isoformat()
    manifest["corrections"] = list((previous or {}).get("corrections", []))
    if args.correction:
        manifest["corrections"].append({"date": datetime.date.today().isoformat(), "reason": args.correction})
    freeze_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Frozen: {len(labels)} receipts. Run: python scripts/eval_extraction.py --test-set")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare the held-out test set.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init").set_defaults(run=cmd_init)
    commands.add_parser("check").set_defaults(run=cmd_check)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("--correction", default=None, help="why a frozen label changed; published with the result")
    freeze.set_defaults(run=cmd_freeze)
    args = parser.parse_args()
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
