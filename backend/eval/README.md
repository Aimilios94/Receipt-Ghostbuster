# Extraction-accuracy eval

Measures how accurately the receipt-extraction pipeline reads real receipts,
field by field, against hand-verified ground truth.

```
backend/eval/
  receipts/            real receipt photos          (git-ignored — personal data)
  labels.json          ground truth for each photo  (git-ignored — personal data)
  labels.example.json  the label format, synthetic  (committed)
  RESULTS.md           aggregate accuracy + guardrail table   (committed — safe to publish)
  MODELS.md            the model comparison, generated from models.json (committed)
  metrics.json         machine-readable aggregates  (committed — served by /metrics/eval)
  badges/              README badges, generated from the results (committed)
  results.detail.json  per-receipt breakdown        (git-ignored)
  test/                the held-out test set: same layout, its own results (photos + labels git-ignored)
  .cache/              cached LLM reads per image    (git-ignored)
```

## Privacy

The receipts and `labels.json` are **real personal spending** (vendors, amounts,
dates), so they are git-ignored and never pushed. Only `RESULTS.md` — which
contains aggregate percentages and a sample size, no per-receipt data — is
committed and quoted in the top-level README.

## Run it

From `backend/` (needs the configured provider's API key in `backend/.env`):

```bash
python scripts/eval_extraction.py            # all receipts, using the per-image cache
python scripts/eval_extraction.py --refresh  # re-call the LLM (ignore cache)
python scripts/eval_extraction.py --limit 3  # first 3 only
python scripts/eval_extraction.py --provider mock   # smoke-test the harness, no API key
```

Each image's read is cached under `.cache/`, so re-runs (e.g. while tweaking the
scorer) cost no API calls until you pass `--refresh`. `eval_models.py` shares this read path
and cache, so `RESULTS.md` and the shipped model's row in `MODELS.md` score the same reads.

## What's scored

The harness runs the **shipped** pipeline — `extraction.extract_receipt` plus the
deterministic `receipt_fields.compute` logic (printed-VAT-table source of truth,
discount scaling, dominant-rate selection, rules + LLM categorization) — i.e. the
fields that actually land on the ledger, not just the raw LLM JSON.

| Field | Match rule |
|---|---|
| `vendor` | fuzzy (substring either way, or a shared ≥4-char token); `vendor_alt` adds acceptable alternates |
| `date` | exact ISO `YYYY-MM-DD` |
| `total` | amount paid, within €0.01 |
| `vat_amount` | within €0.02 |
| `vat_rate` | dominant rate, integer match |
| `category` | exact against the category list |

The held-out set adds one separate score, **VAT per rate**: each printed rate's net, VAT and total against what the app would store. It's reported next to the accuracy above and never added to it, because the development labels have no per-rate figures.

## Guardrail effectiveness & calibration (v0.3.0)

Beyond field accuracy, the harness runs the **shipped review gate**
(`services/gating.decide_gate`) over the same set and compares its decision to
whether each read was actually correct — so it measures whether the guardrails do
their job, not just whether the model reads well:

- **false auto-post rate** — of the reads that were *wrong*, how many still auto-posted (the dangerous miss).
- **over-review rate** — of the *correct* reads, how many were sent to review anyway (friction).
- **confidence calibration** — accuracy grouped by the model's self-reported confidence.

These are written to `RESULTS.md` and to `metrics.json` (aggregates only, committed),
which the `GET /metrics/eval` endpoint serves to the in-app **Model & Evals** page.
An optional `expected_gate` label per receipt (`auto_post` | `review` | `reject`)
adds an expected-vs-actual confusion matrix, but the metrics above need no extra
labelling — they reuse the field ground truth you already have.

## Accuracy-regression gate (CI + local)

`scripts/check_regression.py` fails if any tracked metric drops below a committed
floor (`baseline.json`) minus a tolerance band (`tolerance_pp`, ~1pp to absorb a
re-label; on CACHED reads the pipeline is deterministic so a real regression drops
well past it). It runs in two places:

- **Locally, on the real number** — run before committing any change to the
  scoring / VAT / category / gate code. Reads come from the per-image `.cache/` (deterministic,
  no API cost):

  ```bash
  python scripts/eval_extraction.py        # cached reads -> writes metrics.json
  python scripts/check_regression.py       # gate: metrics.json vs baseline.json
  ```

- **In CI, on the mock mechanism** — the labelled set is git-ignored personal data, so
  the public runner can't check the real number. CI runs the harness in `--provider
  mock` mode to throwaway `*.mock.json` files and gates them against `baseline.mock.json`
  (deterministic, tolerance 0). That catches a code change that silently breaks the
  scoring / VAT / gate pipeline. See `.github/workflows/ci.yml`.

**What the gate can't see.** Reads are cached, and the cache key ignores the prompt, so a
prompt or model change is invisible until you run with `--refresh`. A fresh read is a new
sample from a non-deterministic model: each field's floor is 1pp, so one flipped field on 25
receipts fails the gate. Treat that as a reason to inspect the receipt, not as proof of a
regression ([D50](../../DECISIONS.md)). The gate only watches `eval_extraction.py`, deliberately:
the matrix shares its reads.

**When the set grows or a real improvement lands:** refresh `metrics.json` (a full run),
then update `baseline.json` to the new floors **deliberately** (commit them together),
and run `python scripts/make_badges.py` so the README badges follow; a test fails if they
don't. A changed sample size is surfaced as a non-fatal NOTE by the gate, not a failure.

## Model matrix (`eval_models.py`)

`scripts/eval_models.py` runs the same pipeline across models and writes
`MODELS.md` + `models.json`:

```bash
python scripts/eval_models.py --models ollama:qwen2.5vl-receipt   # re-measure one model
python scripts/eval_models.py --models openai:gpt-5-mini --limit 3  # smoke test, writes nothing
```

A run updates only the models it names. Every other row keeps its numbers and its own
measurement record, and the replaced headline moves to that model's history, so repeat
runs stay visible. `--replace-all` starts a new matrix. The prose in `MODELS.md` lives
under `notes` / `footnotes` in `models.json`; edit it there, because `MODELS.md` is
generated. `tests/test_published_numbers.py` fails if a page or the top-level README stops
matching these results, so refresh the README in the same change as a new run.

A cost is an estimate: the tokens recorded with a read, times the price table in
`app/services/llm_trace.py`. It's worked out again each time, so a price correction reaches saved
reads, and a model that isn't in the table costs 0.0 rather than borrowing a family's price.

A read that fails is declared: its fields count as misses, and the row records how many
reads errored and why. A labelled image missing from disk is declared `NO_DATA` and left
out of that row's denominators. `eval_extraction.py` reports the same way.

## Held-out test set

The 26 receipts above are a development set: some were used to tune the prompts. The test set
in `test/` holds new receipts only, labelled and frozen before any model reads them, and its
results are reported separately. See [test/README.md](test/README.md).

```bash
python scripts/prepare_test_set.py check    # problems with the sheet or the photos
python scripts/prepare_test_set.py freeze   # labels.json + freeze.json
python scripts/eval_extraction.py --test-set
python scripts/eval_models.py --models openai:gpt-4o --test-set
```

Scoring refuses to run if the set isn't frozen, or changed after freezing. `--refresh` doesn't
apply, because the set is read once. A label corrected later needs
`freeze --correction "reason"`, and that reason is printed in the published results.

## LangSmith (optional)

With `LANGSMITH_TRACING=true` + a key, `python scripts/langsmith_eval.py` uploads
this set as a LangSmith **Dataset** and runs the pipeline as a LangSmith
**Experiment** (same field matchers). Opt-in only; the harness above needs none of it.

## Labelling

Each entry in `labels.json` needs a `file`; **every other field is optional** — the
scorer only grades the fields present, so a receipt with no printed VAT simply
isn't scored on VAT. See `labels.example.json` for the shape. To add receipts,
drop images in `receipts/` and add their ground truth to `labels.json`.

`currency` may be included for reference but is **not scored** (see the harness
`FIELDS` note).

### Receipt-type tags (accuracy by slice)

An optional `tags` array labels each receipt by *characteristic* (e.g. `rotated`,
`multi_rate`, `single_rate`, `discount`, `no_vat`, `payment_only`, `crumpled`). The
harness then reports **accuracy by receipt type** — a receipt contributes its field
scores to every tag it carries — so a strong overall average can't hide a weak slice
(e.g. rotated photos reading worse than flat ones). Tags are free-form; add whatever
dimensions matter. The breakdown appears in `RESULTS.md` and under `slices` in
`metrics.json`; an untagged set simply omits the table.
