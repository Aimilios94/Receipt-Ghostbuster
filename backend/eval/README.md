# Extraction-accuracy eval

Measures how accurately the receipt-extraction pipeline reads real receipts,
field by field, against hand-verified ground truth.

```
backend/eval/
  receipts/            real receipt photos          (git-ignored — personal data)
  labels.json          ground truth for each photo  (git-ignored — personal data)
  labels.example.json  the label format, synthetic  (committed)
  RESULTS.md           aggregate accuracy + guardrail table   (committed — safe to publish)
  metrics.json         machine-readable aggregates  (committed — served by /metrics/eval)
  results.detail.json  per-receipt breakdown        (git-ignored)
  .cache/              cached LLM reads per image    (git-ignored)
```

## Privacy

The receipts and `labels.json` are **real personal spending** (vendors, amounts,
dates), so they are git-ignored and never pushed. Only `RESULTS.md` — which
contains aggregate percentages and a sample size, no per-receipt data — is
committed and quoted in the top-level README.

## Run it

From `backend/` (needs `ANTHROPIC_API_KEY` in `backend/.env`):

```bash
python scripts/eval_extraction.py            # all receipts, using the per-image cache
python scripts/eval_extraction.py --refresh  # re-call the LLM (ignore cache)
python scripts/eval_extraction.py --limit 3  # first 3 only
python scripts/eval_extraction.py --provider mock   # smoke-test the harness, no API key
```

Each image's read is cached under `.cache/`, so re-runs (e.g. while tweaking the
scorer) cost no API calls until you pass `--refresh`.

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
