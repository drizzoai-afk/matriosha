-- Matriosha managed Supabase schema (P4.1)
-- Single source of truth for managed Supabase objects.
-- Apply this SQL in Supabase SQL Editor before first deployment.
-- Security posture: owner-scoped RLS for user data, explicit idempotent DDL for safe re-runs.

create extension if not exists pgcrypto;
create extension if not exists vector;

-- users: canonical managed identity mirror of auth.users
create table if not exists public.users (
    id uuid primary key references auth.users(id) on delete cascade,
    created_at timestamptz not null default now()
);
comment on table public.users is 'Managed-mode identity records mapped 1:1 to Supabase auth.users.';

-- profiles: optional per-user display/profile metadata
create table if not exists public.profiles (
    user_id uuid primary key references public.users(id) on delete cascade,
    name text not null,
    created_at timestamptz not null default now()
);
comment on table public.profiles is 'User profile metadata used by managed CLI/account UX.';

-- memories: encrypted payload envelope metadata and base64 payload backup pointer data
create table if not exists public.memories (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.users(id) on delete cascade,
    envelope jsonb not null,
    payload_b64 text not null,
    created_at timestamptz not null default now(),
    tags text[] not null default '{}'
);
comment on table public.memories is 'Encrypted memory payload envelopes owned by each managed user.';

-- memory_vectors: semantic index vectors aligned to memories.id
create table if not exists public.memory_vectors (
    memory_id uuid primary key references public.memories(id) on delete cascade,
    embedding vector(384) not null
);
comment on table public.memory_vectors is 'pgvector embeddings used for managed semantic search/recall.';

-- subscriptions: managed billing contract snapshot per user
create table if not exists public.subscriptions (
    user_id uuid primary key references public.users(id) on delete cascade,
    status text not null,
    current_period_end timestamptz,
    cancel_at timestamptz,
    stripe_customer_id text,
    stripe_subscription_id text,
    stripe_subscription_item_id text,
    plan_code text not null,
    unit_price_cents int not null,
    agent_quota int not null,
    storage_cap_bytes bigint not null,
    storage_used_bytes bigint not null default 0,
    updated_at timestamptz not null default now()
);
comment on table public.subscriptions is 'Current managed Stripe subscription/quota snapshot for enforcement and billing status.';

alter table public.subscriptions add column if not exists stripe_subscription_item_id text;
alter table public.subscriptions add column if not exists cancel_at timestamptz;
alter table public.subscriptions add column if not exists storage_used_bytes bigint not null default 0;
alter table public.subscriptions add column if not exists updated_at timestamptz not null default now();

-- stripe_webhook_events: idempotency ledger for Stripe webhook processing
create table if not exists public.stripe_webhook_events (
    id bigserial primary key,
    event_id text not null,
    event_type text not null,
    processed_at timestamptz not null default now(),
    stripe_data jsonb not null default '{}'::jsonb
);
comment on table public.stripe_webhook_events is 'Stripe webhook event journal for idempotent processing and replay diagnostics.';

alter table public.stripe_webhook_events add column if not exists event_id text;
alter table public.stripe_webhook_events add column if not exists event_type text;
alter table public.stripe_webhook_events add column if not exists processed_at timestamptz not null default now();
alter table public.stripe_webhook_events add column if not exists stripe_data jsonb not null default '{}'::jsonb;

-- quota_usage: explicit storage tracking and breakdown to support quota status UX
create table if not exists public.quota_usage (
    user_id uuid primary key references public.users(id) on delete cascade,
    storage_used_bytes bigint not null default 0,
    raw_storage_bytes bigint not null default 0,
    compressed_storage_bytes bigint not null default 0,
    index_storage_bytes bigint not null default 0,
    updated_at timestamptz not null default now()
);
comment on table public.quota_usage is 'Managed storage usage breakdown (raw/compressed/index) for quota reporting and enforcement.';

alter table public.quota_usage add column if not exists storage_used_bytes bigint not null default 0;
alter table public.quota_usage add column if not exists raw_storage_bytes bigint not null default 0;
alter table public.quota_usage add column if not exists compressed_storage_bytes bigint not null default 0;
alter table public.quota_usage add column if not exists index_storage_bytes bigint not null default 0;
alter table public.quota_usage add column if not exists updated_at timestamptz not null default now();

-- agent_tokens: API tokens minted for managed agent connectivity
create table if not exists public.agent_tokens (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.users(id) on delete cascade,
    token_hash text not null unique,
    name text not null,
    scope text not null default 'write',
    expires_at timestamptz,
    last_used timestamptz,
    created_at timestamptz not null default now(),
    revoked_at timestamptz
);
comment on table public.agent_tokens is 'Hashed managed API tokens issued for agent access.';

alter table public.agent_tokens add column if not exists scope text;
alter table public.agent_tokens add column if not exists expires_at timestamptz;
alter table public.agent_tokens add column if not exists last_used timestamptz;

alter table public.agent_tokens alter column scope set default 'write';
update public.agent_tokens set scope = lower(trim(scope)) where scope is not null;
update public.agent_tokens set scope = 'write' where scope is null or scope not in ('read', 'write', 'admin');
alter table public.agent_tokens alter column scope set not null;

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'agent_tokens_scope_check'
          and conrelid = 'public.agent_tokens'::regclass
    ) then
        alter table public.agent_tokens
            add constraint agent_tokens_scope_check
            check (scope in ('read', 'write', 'admin'));
    end if;
end
$$;

-- agents: connected managed agents linked to issued agent tokens
create table if not exists public.agents (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.users(id) on delete cascade,
    token_id uuid not null references public.agent_tokens(id) on delete cascade,
    name text not null,
    agent_kind text not null,
    fingerprint text not null,
    connected_at timestamptz not null default now(),
    last_seen timestamptz not null default now()
);
comment on table public.agents is 'Connected managed agents and lifecycle telemetry (connect/last_seen).';

-- vault_keys: wrapped data-key custody material (no plaintext data key persisted)
create table if not exists public.vault_keys (
    user_id uuid primary key references public.users(id) on delete cascade,
    wrapped_key bytea not null,
    kdf_salt bytea not null,
    algo text not null default 'aes-gcm',
    rotated_at timestamptz not null default now()
);
comment on table public.vault_keys is 'Wrapped managed vault key material per user for transparent key custody.';

-- Performance indexes
create index if not exists idx_memories_user_id_created_at on public.memories(user_id, created_at desc);
create index if not exists idx_memories_tags on public.memories using gin(tags);
create index if not exists idx_memory_vectors_embedding_ivfflat
    on public.memory_vectors
    using ivfflat (embedding vector_cosine_ops)
    with (lists = 100);
create index if not exists idx_agent_tokens_user_id_created_at on public.agent_tokens(user_id, created_at desc);
create index if not exists idx_agents_user_id_connected_at on public.agents(user_id, connected_at desc);
create index if not exists idx_subscriptions_status on public.subscriptions(status);
create index if not exists idx_subscriptions_stripe_customer on public.subscriptions(stripe_customer_id);
create index if not exists idx_subscriptions_stripe_subscription on public.subscriptions(stripe_subscription_id);
create index if not exists idx_subscriptions_stripe_item on public.subscriptions(stripe_subscription_item_id);
create unique index if not exists uq_stripe_webhook_events_event_id on public.stripe_webhook_events(event_id);
create index if not exists idx_stripe_webhook_events_type_processed on public.stripe_webhook_events(event_type, processed_at desc);
create index if not exists idx_quota_usage_updated_at on public.quota_usage(updated_at desc);

-- RLS enablement
alter table public.users enable row level security;
alter table public.profiles enable row level security;
alter table public.memories enable row level security;
alter table public.memory_vectors enable row level security;
alter table public.subscriptions enable row level security;
alter table public.stripe_webhook_events enable row level security;
alter table public.quota_usage enable row level security;
alter table public.agent_tokens enable row level security;
alter table public.agents enable row level security;
alter table public.vault_keys enable row level security;

create or replace function public.check_token_scope(required text)
returns boolean
language sql
stable
as $$
    with raw_scope as (
        select nullif(current_setting('request.jwt.claim.scope', true), '') as scope
    ),
    normalized as (
        select lower(trim(value)) as scope
        from raw_scope,
        lateral unnest(regexp_split_to_array(coalesce(raw_scope.scope, ''), '[,[:space:]]+')) as value
    )
    select exists (
        select 1
        from normalized
        where normalized.scope = lower(trim(required))
    );
$$;

-- users: self-only access
drop policy if exists users_select_own on public.users;
create policy users_select_own on public.users
    for select using (id = auth.uid());
drop policy if exists users_insert_own on public.users;
create policy users_insert_own on public.users
    for insert with check (id = auth.uid());
drop policy if exists users_update_own on public.users;
create policy users_update_own on public.users
    for update using (id = auth.uid()) with check (id = auth.uid());

-- profiles: user_id = auth.uid()
drop policy if exists profiles_select_own on public.profiles;
create policy profiles_select_own on public.profiles
    for select using (user_id = auth.uid());
drop policy if exists profiles_insert_own on public.profiles;
create policy profiles_insert_own on public.profiles
    for insert with check (user_id = auth.uid());
drop policy if exists profiles_update_own on public.profiles;
create policy profiles_update_own on public.profiles
    for update using (user_id = auth.uid()) with check (user_id = auth.uid());
drop policy if exists profiles_delete_own on public.profiles;
create policy profiles_delete_own on public.profiles
    for delete using (user_id = auth.uid());

-- memories: user_id = auth.uid() + scope checks
drop policy if exists memories_select_own on public.memories;
create policy memories_select_own on public.memories
    for select using (
        user_id = auth.uid()
        and (
            public.check_token_scope('read')
            or public.check_token_scope('write')
            or public.check_token_scope('admin')
        )
    );
drop policy if exists memories_insert_own on public.memories;
create policy memories_insert_own on public.memories
    for insert with check (
        user_id = auth.uid()
        and (
            public.check_token_scope('write')
            or public.check_token_scope('admin')
        )
    );
drop policy if exists memories_update_own on public.memories;
create policy memories_update_own on public.memories
    for update using (
        user_id = auth.uid()
        and (
            public.check_token_scope('write')
            or public.check_token_scope('admin')
        )
    )
    with check (
        user_id = auth.uid()
        and (
            public.check_token_scope('write')
            or public.check_token_scope('admin')
        )
    );
drop policy if exists memories_delete_own on public.memories;
create policy memories_delete_own on public.memories
    for delete using (
        user_id = auth.uid()
        and public.check_token_scope('admin')
    );

-- memory_vectors inherits owner scope through memories join
drop policy if exists memory_vectors_select_own on public.memory_vectors;
create policy memory_vectors_select_own on public.memory_vectors
    for select using (
        exists (
            select 1
            from public.memories m
            where m.id = memory_vectors.memory_id
              and m.user_id = auth.uid()
        )
    );
drop policy if exists memory_vectors_insert_own on public.memory_vectors;
create policy memory_vectors_insert_own on public.memory_vectors
    for insert with check (
        exists (
            select 1
            from public.memories m
            where m.id = memory_vectors.memory_id
              and m.user_id = auth.uid()
        )
    );
drop policy if exists memory_vectors_update_own on public.memory_vectors;
create policy memory_vectors_update_own on public.memory_vectors
    for update using (
        exists (
            select 1
            from public.memories m
            where m.id = memory_vectors.memory_id
              and m.user_id = auth.uid()
        )
    )
    with check (
        exists (
            select 1
            from public.memories m
            where m.id = memory_vectors.memory_id
              and m.user_id = auth.uid()
        )
    );
drop policy if exists memory_vectors_delete_own on public.memory_vectors;
create policy memory_vectors_delete_own on public.memory_vectors
    for delete using (
        exists (
            select 1
            from public.memories m
            where m.id = memory_vectors.memory_id
              and m.user_id = auth.uid()
        )
    );

-- subscriptions: user_id = auth.uid()
drop policy if exists subscriptions_select_own on public.subscriptions;
create policy subscriptions_select_own on public.subscriptions
    for select using (user_id = auth.uid());
drop policy if exists subscriptions_insert_own on public.subscriptions;
create policy subscriptions_insert_own on public.subscriptions
    for insert with check (user_id = auth.uid());
drop policy if exists subscriptions_update_own on public.subscriptions;
create policy subscriptions_update_own on public.subscriptions
    for update using (user_id = auth.uid()) with check (user_id = auth.uid());
drop policy if exists subscriptions_delete_own on public.subscriptions;
create policy subscriptions_delete_own on public.subscriptions
    for delete using (user_id = auth.uid());

-- quota_usage: user_id = auth.uid()
drop policy if exists quota_usage_select_own on public.quota_usage;
create policy quota_usage_select_own on public.quota_usage
    for select using (user_id = auth.uid());
drop policy if exists quota_usage_insert_own on public.quota_usage;
create policy quota_usage_insert_own on public.quota_usage
    for insert with check (user_id = auth.uid());
drop policy if exists quota_usage_update_own on public.quota_usage;
create policy quota_usage_update_own on public.quota_usage
    for update using (user_id = auth.uid()) with check (user_id = auth.uid());
drop policy if exists quota_usage_delete_own on public.quota_usage;
create policy quota_usage_delete_own on public.quota_usage
    for delete using (user_id = auth.uid());

-- stripe_webhook_events: no per-user policy; service role manages writes/reads.
drop policy if exists stripe_webhook_events_select_none on public.stripe_webhook_events;
create policy stripe_webhook_events_select_none on public.stripe_webhook_events
    for select using (false);
drop policy if exists stripe_webhook_events_insert_none on public.stripe_webhook_events;
create policy stripe_webhook_events_insert_none on public.stripe_webhook_events
    for insert with check (false);
drop policy if exists stripe_webhook_events_update_none on public.stripe_webhook_events;
create policy stripe_webhook_events_update_none on public.stripe_webhook_events
    for update using (false) with check (false);
drop policy if exists stripe_webhook_events_delete_none on public.stripe_webhook_events;
create policy stripe_webhook_events_delete_none on public.stripe_webhook_events
    for delete using (false);

-- agent_tokens: user_id = auth.uid()
drop policy if exists agent_tokens_select_own on public.agent_tokens;
create policy agent_tokens_select_own on public.agent_tokens
    for select using (user_id = auth.uid());
drop policy if exists agent_tokens_insert_own on public.agent_tokens;
create policy agent_tokens_insert_own on public.agent_tokens
    for insert with check (user_id = auth.uid());
drop policy if exists agent_tokens_update_own on public.agent_tokens;
create policy agent_tokens_update_own on public.agent_tokens
    for update using (user_id = auth.uid()) with check (user_id = auth.uid());
drop policy if exists agent_tokens_delete_own on public.agent_tokens;
create policy agent_tokens_delete_own on public.agent_tokens
    for delete using (user_id = auth.uid());

-- agents: user_id = auth.uid()
drop policy if exists agents_select_own on public.agents;
create policy agents_select_own on public.agents
    for select using (user_id = auth.uid());
drop policy if exists agents_insert_own on public.agents;
create policy agents_insert_own on public.agents
    for insert with check (user_id = auth.uid());
drop policy if exists agents_update_own on public.agents;
create policy agents_update_own on public.agents
    for update using (user_id = auth.uid()) with check (user_id = auth.uid());
drop policy if exists agents_delete_own on public.agents;
create policy agents_delete_own on public.agents
    for delete using (user_id = auth.uid());

-- vault_keys: user_id = auth.uid()
drop policy if exists vault_keys_select_own on public.vault_keys;
create policy vault_keys_select_own on public.vault_keys
    for select using (user_id = auth.uid());
drop policy if exists vault_keys_insert_own on public.vault_keys;
create policy vault_keys_insert_own on public.vault_keys
    for insert with check (user_id = auth.uid());
drop policy if exists vault_keys_update_own on public.vault_keys;
create policy vault_keys_update_own on public.vault_keys
    for update using (user_id = auth.uid()) with check (user_id = auth.uid());
drop policy if exists vault_keys_delete_own on public.vault_keys;
create policy vault_keys_delete_own on public.vault_keys
    for delete using (user_id = auth.uid());

-- Edge function prerequisites for server custody operations:
--   1) create pgsodium-backed RPC `vault_seal_box(plaintext_b64 text)`.
--   2) create pgsodium-backed RPC `vault_open_box(sealed_b64 text)`.
--   3) edge function `vault-custody` calls these RPCs and writes only wrapped bytes here.
