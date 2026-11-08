# Setup

Everything beyond the README's [Quickstart](../README.md#quickstart).

## Prerequisites

- **Python 3.12+** (CI runs 3.12; developed on 3.14) and **Node 18+**
- A **Supabase** project
- An **OpenAI API key.** The default model is `gpt-5-mini`, and the Ask chatbot needs OpenAI. Receipts can also be read with Anthropic, Mistral or a local Ollama model.

## Configure

1. Copy `backend/.env.example` to `backend/.env` and fill it in.
2. Create a user under Supabase → Authentication → Users, and set `DEV_USER_ID` to its UUID.
3. Copy `frontend/.env.example` to `frontend/.env`. It defaults to `VITE_API_BASE_URL=http://localhost:8000`.

> **Keep the backend on localhost.** The frontend has no login yet, so with `DEV_USER_ID` set, any request without a token acts as that user, deletes included.

## Install

**macOS / Linux**
```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
# needs SUPABASE_ACCESS_TOKEN in .env, or paste db/schema.sql into the Supabase SQL editor
.venv/bin/python scripts/apply_schema.py

cd ../frontend
npm install
```

**Windows (PowerShell)**
```powershell
cd backend
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# needs SUPABASE_ACCESS_TOKEN in .env, or paste db/schema.sql into the Supabase SQL editor
.\.venv\Scripts\python.exe scripts\apply_schema.py

cd ..\frontend
npm install
```

## Run

Run one backend process with no `--reload`, which orphans the port on Windows. Replace `.venv/bin/python` with `.\.venv\Scripts\python.exe` on Windows.

```bash
# terminal 1: API on :8000, docs at http://localhost:8000/docs
cd backend
.venv/bin/python -m uvicorn app.main:app --port 8000

# terminal 2: UI on :5173
cd frontend
npm run dev
```

## Load the sample data

With the backend running, in a third terminal:

```bash
cd backend
.venv/bin/python scripts/load_sample_data.py    # expenses + bank CSV + reconcile
.venv/bin/python scripts/load_phase2_demo.py    # optional: recurring charges for Refund Hunter
```

These post into the ledger of `DEV_USER_ID`. If that ledger holds real data, point `DEV_USER_ID` at a separate user first.

## Optional

- **Gmail drafts for Refund Hunter:** needs n8n. See [n8n/README.md](../n8n/README.md).
- **Local, on-device reading:** set `LLM_PROVIDER=ollama`. See the comments in `backend/.env.example`. Ask doesn't work on this provider.
- **Error tracking and tracing:** see [MONITORING.md](MONITORING.md). Both are off by default.
- **A public read-only demo:** set `DEMO_READ_ONLY=true` on the backend and `VITE_DEMO_READ_ONLY=true` on the frontend. Every write and paid call is refused, and a banner says so. Use a separate Supabase project and user holding only sample data, set `LLM_PROVIDER=mock` with no model key, and set `CORS_ORIGINS` to the site's address. `backend/vercel.json` and `frontend/vercel.json` deploy each folder as its own Vercel project, and each folder's `.vercelignore` uploads only the code. Load the sample data before turning read-only on ([D57](../DECISIONS.md)).

## Tests and evals

```bash
cd backend
.venv/bin/python -m pytest -q
```

The evals are documented in [backend/eval/README.md](../backend/eval/README.md) and [backend/eval/chatbot/README.md](../backend/eval/chatbot/README.md).

## Demo walkthrough

The sample dataset is shaped so every reconciliation path shows up.

1. **Dashboard:** click any number to open the expenses behind it.
2. **Add → Snap a receipt:** a confident read auto-posts, and a shaky one lands in the **Review queue** with reasons.
3. **Add → Manual / cash:** cash counts in totals but is never a reconciliation exception.
4. **Reconciliation:** run it and walk the exceptions. **Resolve** on the duplicate filters the Ledger to the flagged pair.
5. **Monthly close:** money in and out, VAT, and a check that stays blocked while card items are unreconciled. Closing saves the month's figures, and the page lists anything that changes afterwards; the month isn't locked.
6. **Refund Hunter:** subscriptions by annual cost. Draft a cancellation, then **Save to Gmail drafts**.
7. **Advice:** budget vs actual and rule-based nudges, each linking to the fix.
8. **Ask:** try *"my top 3 days in October"* and click a row. Out-of-scope questions are declined.
9. **Model & Evals:** extraction accuracy, guardrail effectiveness, and live latency and cost.
