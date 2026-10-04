# n8n workflows (Phase 2 — Refund Hunter delivery)

n8n is the **orchestration + delivery layer**. The core logic (detection, draft
writing, savings) lives in FastAPI; n8n only (a) turns an approved draft into a
real **Gmail draft** — never a sent email — and (b) re-runs detection on a cron.

Two workflows:

| File | What it does |
|---|---|
| `refund-draft-to-gmail.json` | **Webhook** (`POST /webhook/refund-draft`) → **Gmail: Create Draft**. The backend forwards `{to, subject, message}` here when you click "Save to Gmail drafts". |
| `detect-subscriptions-cron.json` | **Schedule** (weekly) → **HTTP Request** `POST http://host.docker.internal:8000/subscriptions/detect`. Keeps subscriptions fresh automatically. |

## Run n8n (Docker)

```bash
docker run -d --name receipt-ghostbuster-n8n -p 5678:5678 \
  -v rg_n8n_data:/home/node/.n8n n8nio/n8n
```

Open **http://localhost:5678** and create the owner account (local only).

> From inside the container, the backend is reachable at `http://host.docker.internal:8000`,
> **not** `localhost` (localhost inside a container is the container itself).

## One-time: connect Gmail

The Gmail node needs a Google OAuth credential (Gmail API). In n8n:

1. **Credentials → New → Gmail OAuth2 API**.
2. In [Google Cloud Console](https://console.cloud.google.com): create a project →
   enable the **Gmail API** → **OAuth consent screen** (External, add yourself as a
   test user) → **Credentials → OAuth client ID → Web application**. Set the
   **Authorized redirect URI** to the value n8n shows on the credential screen
   (`http://localhost:5678/rest/oauth2-credential/callback`).
3. Paste the **Client ID** and **Client Secret** into n8n, click **Sign in with
   Google**, approve the `gmail.modify` scope.

## Import the workflows

1. n8n → **Workflows → Import from File** → pick each JSON in this folder.
2. Open `refund-draft-to-gmail`, click the **Gmail - Create Draft** node and select
   your Gmail credential (and verify the field mappings). **Save**, then **Activate**.
3. Open `detect-subscriptions-cron` and **Activate** it (no credential needed).

## Wire the backend to the webhook

With the webhook workflow **active**, copy its Production URL (it will be
`http://localhost:5678/webhook/refund-draft`) and set it in `backend/.env`:

```
N8N_WEBHOOK_URL=http://localhost:5678/webhook/refund-draft
```

Restart the backend. `GET /health` will now report `n8n_configured: true`, and the
**"Save to Gmail drafts"** button in Refund Hunter becomes active. Clicking it posts
the approved draft to n8n, which creates a Gmail draft in your account —
**ready for you to review and send yourself. Nothing is ever sent automatically.**
