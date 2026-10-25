# Chatbot eval

Measures the quality of the NL Q&A chatbot (`/ask`, [D40](../../../DECISIONS.md)). The
chatbot answers **only** by calling the fixed analytics tools in `app/services/analytics.py`;
every number is computed in code, the model never does arithmetic ([D1]). So the LLM's real
job is **picking the right tool with the right arguments** — that is what this harness scores.

```
backend/eval/chatbot/
  ledger.json          synthetic fixed test ledger        (COMMITTED — not real data)
  questions.json       labelled eval set + ground truth   (COMMITTED)
  baseline.json        live-number regression floor        (COMMITTED)
  baseline.mock.json   offline-check regression floor      (COMMITTED)
  metrics.json         live aggregates (tool-sel/answer/refusal)   (COMMITTED)
  RESULTS.md           human-readable aggregate table      (COMMITTED — safe to publish)
  .cache/              cached live model responses          (git-ignored)
  results.detail.json  per-question breakdown               (git-ignored)
  *.mock.*             throwaway outputs of the offline check (git-ignored)
```

Unlike the extraction eval (`backend/eval/`), whose receipts + labels are **real personal
spending** and therefore git-ignored, this ledger is **synthetic and committed** — so the
whole chatbot eval is reproducible by anyone and safe to run in CI.

## What's scored (see `docs/design/chatbot.md` → Evaluation)

| Metric | How | Needs the model? |
|---|---|---|
| **answer_correctness** | dispatch the tool over the fixed ledger, deep-subset-compare the structured result to the expected figure — graded in **code**, no judge | no — deterministic |
| **tool_selection** | did the model call the right analytics tool with the right args (`used_tools`)? the key metric | yes |
| **refusal** | out-of-scope questions (weather, stock tips, another user's data) must call **no** tool | yes |

Prose faithfulness (does the sentence follow from the numbers?) is **not** graded here — that
is the calibrated LLM-as-judge planned for Slice 3. We only verify the figure is tool-derived.

## Run it

From `backend/`:

```bash
# offline, deterministic, no API key — this is what CI runs
python scripts/eval_chatbot.py --check \
  --metrics-out eval/chatbot/metrics.mock.json \
  --results-out eval/chatbot/RESULTS.mock.md \
  --detail-out  eval/chatbot/results.detail.mock.json
python scripts/check_regression.py \
  --metrics eval/chatbot/metrics.mock.json --baseline eval/chatbot/baseline.mock.json

# the real numbers (needs OPENAI_API_KEY, LLM_PROVIDER=openai); cached per question
python scripts/eval_chatbot.py --live           # writes metrics.json + RESULTS.md
python scripts/eval_chatbot.py --live --refresh  # ignore the cache, re-call gpt-5-mini
python scripts/check_regression.py \
  --metrics eval/chatbot/metrics.json --baseline eval/chatbot/baseline.json
```

The live run caches each model response under `.cache/` keyed on the question + a ledger
fingerprint + the model, so re-runs are free and the gate is deterministic in practice.

## Two gates, mirroring the extraction eval

- **CI, deterministic** — `--check` dispatches every tool over the fixed ledger (no key, no
  network) and gates `answer_correctness` against `baseline.mock.json` (tolerance 0). This
  can't measure the model, but it catches any change that breaks the analytics surface or the
  scoring. See `.github/workflows/ci.yml`.
- **Local, live** — `--live` runs gpt-5-mini and gates `tool_selection` + `answer_correctness`
  + `refusal` against `baseline.json`. The model layer is non-deterministic, so the floors sit
  below the observed number with a tolerance band; refresh them deliberately with the
  `metrics.json` they came from.

## Labelling

Each `questions.json` entry is `{id, kind, question, ...}`:
- `kind: "answerable"` needs an `expected_tool` (`{name, args}`, or a **list** of acceptable
  alternatives) and an `expected_answer` that must be a **deep subset** of the tool result
  (floats within €0.01, lists matched by membership — pin only the figures that matter).
- `kind: "refusal"` needs no tool — a correct refusal calls no analytics tool.

`questions.json` carries a fixed `today` (`2026-10-31`) so "this month" questions are
deterministic. To grow the set: add questions (and, if needed, rows to `ledger.json`), re-run
`--check` to confirm the ground truth, then `--live` and refresh `baseline.json`/`metrics.json`.
