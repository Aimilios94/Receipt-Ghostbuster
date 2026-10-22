# Data handling & privacy

Receipt Ghostbuster processes **personal financial data** — receipt photos, bank
statements, and the ledger derived from them. This document states plainly what data
is handled, where it goes, and the controls that exist. It describes the software as
built; it is not legal advice.

## What data the app handles

- **Receipt images** you upload (stored, and read by a vision model).
- **Bank statements** (CSV or PDF) you import — dates, descriptions, amounts, and
  whatever else the file contains (an IBAN or card number may appear in the text).
- **Derived records** — expenses, VAT splits, categories, reconciliation links, the
  monthly close, detected subscriptions.
- **Per-read observability** — latency, token counts and estimated cost of each model
  call (no card/account numbers), used by the Model & Evals page.

## Where it goes

| Data | Destination | Notes |
|---|---|---|
| Receipt image | The configured vision model | **Cloud** (OpenAI or Anthropic) **or local** (Ollama, on-device) — your choice, see below. |
| Bank-PDF text | The configured LLM, **only if cloud** | Text is extracted locally (`pdfplumber`); IBAN/card numbers are **redacted before sending** (see below). |
| Bank CSV | Nowhere external | Parsed entirely in code — **no LLM, no network**. |
| Ledger, images, statements | Supabase (Postgres + storage) | Your own project; secrets stay server-side, never in the browser. |
| Prompts + images (LangSmith) | LangSmith cloud | **Opt-in, off by default** — only if you set `LANGSMITH_TRACING=true`. |
| Refund-draft email | Gmail **draft** via n8n | Draft-only; nothing is ever sent automatically. |

## The local-model option (data never leaves the machine)

The reading model is pluggable. With `LLM_PROVIDER=ollama` the receipt is read by a
**local vision model** (e.g. `qwen2.5vl:7b`) through [Ollama](https://ollama.com) — the
image and prompt **never leave your computer**. This is the privacy-maximising choice
for financial documents. It trades speed and some accuracy for locality; that trade-off
is **measured**, not asserted — see the local column in
[`backend/eval/MODELS.md`](../backend/eval/MODELS.md).

Cloud providers (OpenAI/Anthropic) are faster and currently more accurate, and under
their API terms do not train on inputs by default — but the data does leave the machine.
Choose per your risk tolerance.

## Redaction

Before any bank-statement **text** is sent to a cloud LLM for structuring, IBANs and
card numbers are masked (`app/services/redaction.py`, unit-tested). The structuring only
needs `date / description / amount`, so account identifiers are stripped out — the
provider never receives a number it has no reason to hold.

Receipt **images** cannot be text-redacted. The honest mitigation there is the
**local model** option above (and keeping the LangSmith tracer off).

## Retention & deletion

- Expenses, statements and subscriptions are **deletable** from the app; deleting an
  expense removes its ledger row.
- Receipt images live in your Supabase storage bucket; manage or purge them in your own
  Supabase project.
- Nothing is sold or shared. There is no third-party analytics beyond the **opt-in**
  LangSmith tracer. Cloud model providers may retain API inputs per their own data-usage
  policies — review OpenAI's / Anthropic's terms if you use the cloud path.

## Roles (plain-language)

This is a **single-user personal tool**: you are the data subject and you control your
own data. The model provider and Supabase act as processors under their respective
terms. For an EU user handling Portuguese receipts, the local-model path keeps the most
sensitive step (reading the document) entirely on your own hardware.
