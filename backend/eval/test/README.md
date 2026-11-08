# Held-out test set

The 26 receipts in `backend/eval/` are a development set, because some were used to tune the prompts. This set answers the question that one can't: how does the pipeline do on receipts it has never seen?

The photos, `labels.json` and `true-values.csv` are personal data and stay on this machine. Only the aggregate results and the hashes in `freeze.json` are committed.

Results: [RESULTS.md](RESULTS.md) for the model in use and [MODELS.md](MODELS.md) for the comparison. The notes at the top of `MODELS.md` say what this set can and can't show.

## The rules

1. **New receipts only.** A receipt already uploaded to the app or read by an eval doesn't qualify.
2. **True values first.** Write them from the paper before any model reads the photo.
3. **Only what's printed.** If the paper doesn't show it, leave it blank, even if you know the answer.
4. **Read once, no tuning afterwards.** No prompt changes before scoring, and the result is published whatever it is.

## Adding receipts

1. Put the photos in `receipts/`. Don't upload them to the app until the set is scored.
2. Fill in `true-values.csv`, one row per photo. It opens in Excel. From `backend/`, `python scripts/prepare_test_set.py init` adds a row for each photo, so you don't have to type the file names.
3. Run `python scripts/prepare_test_set.py check` and fix anything it reports.

`true-values.template.csv` shows two made-up examples.

`check` also catches typos in `vat_lines`: each row's net + VAT must equal its total, the rows must add up to `total` and `vat_amount`, and `vat_rate` must be the rate with the largest total.

## What to write in each column

| Column | What to write | If it isn't printed |
|---|---|---|
| `file` | The photo's file name, e.g. `example.jpg` | Required |
| `vendor` | The shop's name as printed | Leave blank |
| `also_accept` | Any other name printed on the receipt, e.g. a payment company and a merchant. Separate names with `\|` | Leave blank |
| `date` | The purchase date, day first: `13/03/2026` | Leave blank |
| `total` | The amount you **paid**, after any discounts: `8,50` | Required |
| `vat_amount` | The total VAT printed, across all rates: `2,13` | Leave blank |
| `vat_rate` | The rate with the largest total in the VAT table, which is what the app stores as the main rate: `13`. If there's only one rate, that one | Leave blank |
| `vat_lines` | Every row of the VAT table as `rate: net / VAT / total`, separated with `\|`: `6%: 10,00 / 0,60 / 10,60 \| 23%: 1,00 / 0,23 / 1,23` | Leave blank |
| `category` | One of the categories below, if the receipt makes it clear | Leave blank |
| `tags` | What makes this receipt hard or different, separated by commas | Leave blank |
| `note` | Anything for yourself. It isn't scored | Leave blank |

**Categories:** Groceries · Dining & Cafes · Transport & Fuel · Utilities · Rent & Housing · Software & Subscriptions · Office & Supplies · Travel · Health & Pharmacy · Entertainment · Professional Services · Taxes & Fees · Tobacco · Income

**Suggested tags:** `upright` · `rotated` · `crumpled` · `bad_light` · `multi_rate` · `single_rate` · `discount` · `no_vat` · `payment_only` · `new_store` · `other_language`

## Scoring (after the rules above)

```bash
cd backend
python scripts/prepare_test_set.py freeze
python scripts/eval_extraction.py --test-set
python scripts/eval_models.py --models openai:gpt-4o anthropic:claude-haiku-4-5 --test-set
```

`vat_lines` feeds a separate score, VAT per rate, reported next to the main accuracy and never added to it. That keeps the main number comparable with the development set, whose labels have no per-rate figures.

If a true value turns out to be mistyped after scoring, `freeze --correction "reason"` updates it, and the reason is printed in the published results.

## A later batch

This set is frozen, so new receipts never join it. A later batch gets its own folder under `eval/`, named `test-` plus a suffix such as the month (`test-2026-11`), with its own photos, sheet, freeze, results and model matrix. The same rules apply, and a photo already in another held-out set is refused. Every command takes `--set`:

```bash
cd backend
python scripts/prepare_test_set.py init --set test-2026-11
python scripts/prepare_test_set.py check --set test-2026-11
python scripts/prepare_test_set.py freeze --set test-2026-11
python scripts/eval_extraction.py --set test-2026-11
python scripts/eval_models.py --models anthropic:claude-haiku-5-5 --set test-2026-11
```

Each batch is published on its own, with its own n and date, and is never added to this one.
