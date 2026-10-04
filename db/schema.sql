-- ============================================================================
-- Receipt Ghostbuster — Phase 1 schema (Supabase / Postgres)
-- Run this in the Supabase SQL editor on a fresh project.
-- RLS: single authenticated owner. Every row is scoped to auth.uid().
-- ============================================================================

-- Extensions ----------------------------------------------------------------
create extension if not exists "pgcrypto";      -- gen_random_uuid()

-- ----------------------------------------------------------------------------
-- ENUM-like check constraints are used inline (portable, easy to read).
-- ----------------------------------------------------------------------------

-- categories -----------------------------------------------------------------
create table if not exists public.categories (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null default auth.uid() references auth.users (id) on delete cascade,
  name          text not null,
  parent_id     uuid references public.categories (id) on delete set null,
  budget_amount numeric(12,2),                    -- nullable; used in Phase 3
  created_at    timestamptz not null default now(),
  unique (user_id, name)
);

-- expenses -------------------------------------------------------------------
-- The core ledger. One row per expense, whether snapped or hand-typed.
create table if not exists public.expenses (
  id                    uuid primary key default gen_random_uuid(),
  user_id               uuid not null default auth.uid() references auth.users (id) on delete cascade,
  source                text not null check (source in ('card','bank','cash')),
  input_method          text not null check (input_method in ('receipt','manual')),
  vendor                text,
  amount                numeric(12,2) not null,
  currency              text not null default 'EUR',
  expense_date          date not null,
  category              text,
  vat_amount            numeric(12,2),
  vat_rate              numeric(5,2),              -- e.g. 24.00 (%)
  note                  text,
  receipt_image_url     text,
  confidence            numeric(4,3),              -- 0.000–1.000, null for manual
  status                text not null default 'posted'
                          check (status in ('pending_review','confirmed','posted')),
  reconciled            boolean not null default false,
  matched_transaction_id uuid,                     -- FK added after bank_transactions exists
  raw_extraction        jsonb,                     -- full LLM payload for audit
  created_at            timestamptz not null default now()
);

-- bank_transactions ----------------------------------------------------------
-- Imported from an uploaded bank-statement CSV.
create table if not exists public.bank_transactions (
  id                 uuid primary key default gen_random_uuid(),
  user_id            uuid not null default auth.uid() references auth.users (id) on delete cascade,
  txn_date           date not null,
  description        text,
  amount             numeric(12,2) not null,       -- signed: negative = money out
  balance            numeric(12,2),
  source_file        text,
  matched_expense_id uuid references public.expenses (id) on delete set null,
  raw                jsonb,
  created_at         timestamptz not null default now()
);

-- Now that bank_transactions exists, wire the expenses -> bank FK.
do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'expenses_matched_transaction_id_fkey'
  ) then
    alter table public.expenses
      add constraint expenses_matched_transaction_id_fkey
      foreign key (matched_transaction_id)
      references public.bank_transactions (id) on delete set null;
  end if;
end $$;

-- Helpful indexes ------------------------------------------------------------
create index if not exists idx_expenses_user_date   on public.expenses (user_id, expense_date);
create index if not exists idx_expenses_status      on public.expenses (user_id, status);
create index if not exists idx_expenses_reconciled  on public.expenses (user_id, reconciled);
create index if not exists idx_bank_user_date       on public.bank_transactions (user_id, txn_date);
create index if not exists idx_bank_matched         on public.bank_transactions (user_id, matched_expense_id);

-- ============================================================================
-- Row Level Security — authenticated owner only
-- ============================================================================
alter table public.categories         enable row level security;
alter table public.expenses           enable row level security;
alter table public.bank_transactions  enable row level security;

-- One policy per table covering all verbs; owner = auth.uid().
drop policy if exists categories_owner on public.categories;
create policy categories_owner on public.categories
  for all to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

drop policy if exists expenses_owner on public.expenses;
create policy expenses_owner on public.expenses
  for all to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

drop policy if exists bank_txn_owner on public.bank_transactions;
create policy bank_txn_owner on public.bank_transactions
  for all to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

-- NOTE on the backend service_role key:
-- The FastAPI backend uses the service_role key, which BYPASSES RLS. The backend
-- must therefore always set user_id explicitly on insert and filter by user_id on
-- read. RLS above is the safety net for any direct supabase-js access from the
-- frontend (which uses the anon key + the signed-in user's JWT).

-- ============================================================================
-- Storage bucket for receipt images
-- ============================================================================
insert into storage.buckets (id, name, public)
values ('receipts', 'receipts', false)
on conflict (id) do nothing;

-- Owner-scoped storage policies. Convention: objects are stored under a path
-- prefixed with the user's id, e.g. "<user_id>/<uuid>.jpg".
drop policy if exists receipts_owner_read on storage.objects;
create policy receipts_owner_read on storage.objects
  for select to authenticated
  using (bucket_id = 'receipts' and owner = auth.uid());

drop policy if exists receipts_owner_write on storage.objects;
create policy receipts_owner_write on storage.objects
  for insert to authenticated
  with check (bucket_id = 'receipts' and owner = auth.uid());

-- ============================================================================
-- Default categories are seeded PER USER by the backend on first use
-- (see backend/app/repository.py:seed_default_categories). We intentionally do
-- NOT seed them here: in the SQL editor auth.uid() is NULL, which would violate
-- the NOT NULL user_id and fail this whole script.
-- ============================================================================


-- ============================================================================
-- Phase 2 — Refund Hunter
-- Recurring-charge detection + draft cancel/refund actions (draft-only).
-- ============================================================================

-- subscriptions --------------------------------------------------------------
-- One row per detected recurring charge (same vendor + same amount over time).
-- Detection-derived columns are refreshed by POST /subscriptions/detect; the
-- user-owned columns (status, usage_note) are preserved across re-detection.
create table if not exists public.subscriptions (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null default auth.uid() references auth.users (id) on delete cascade,
  vendor        text not null,
  amount        numeric(12,2) not null,                 -- per-charge amount
  cadence       text not null default 'monthly'
                  check (cadence in ('weekly','monthly','quarterly','yearly','unknown')),
  annual_cost   numeric(12,2),                          -- amount x periods/year
  occurrences   integer not null default 1,             -- distinct charge dates seen
  first_seen    date,
  last_seen     date,
  source        text not null default 'bank'
                  check (source in ('bank','card','mixed')),
  status        text not null default 'active'          -- user-owned
                  check (status in ('active','flagged','cancelled')),
  usage_note    text,                                   -- user-owned
  created_at    timestamptz not null default now(),
  unique (user_id, vendor, amount)                      -- idempotent upsert key
);

-- refund_actions -------------------------------------------------------------
-- A drafted cancel/refund email for a subscription. ALWAYS draft-only until the
-- user approves and sends (Phase 2 T14). Gmail delivery is handled by n8n.
create table if not exists public.refund_actions (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null default auth.uid() references auth.users (id) on delete cascade,
  subscription_id uuid not null references public.subscriptions (id) on delete cascade,
  action          text not null default 'cancel' check (action in ('cancel','refund')),
  recipient       text,                                 -- where the draft would go
  subject         text,
  email_draft     text,
  status          text not null default 'draft'
                    check (status in ('draft','sent','done')),
  saved_amount    numeric(12,2),                        -- recorded on cancel (T15)
  created_at      timestamptz not null default now()
);

create index if not exists idx_subscriptions_user   on public.subscriptions (user_id, status);
create index if not exists idx_refund_actions_user   on public.refund_actions (user_id, status);
create index if not exists idx_refund_actions_sub    on public.refund_actions (subscription_id);

alter table public.subscriptions  enable row level security;
alter table public.refund_actions enable row level security;

drop policy if exists subscriptions_owner on public.subscriptions;
create policy subscriptions_owner on public.subscriptions
  for all to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

drop policy if exists refund_actions_owner on public.refund_actions;
create policy refund_actions_owner on public.refund_actions
  for all to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());
