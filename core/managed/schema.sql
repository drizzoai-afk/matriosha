-- Matriosha managed Supabase schema (P4.1)
-- Security: owner-scoped RLS for all user tables.

create extension if not exists vector;

create table if not exists public.users (
    id uuid primary key references auth.users(id) on delete cascade,
    created_at timestamptz not null default now()
);

create table if not exists public.profiles (
    user_id uuid primary key references public.users(id) on delete cascade,
    name text not null,
    created_at timestamptz not null default now()
);

create table if not exists public.memories (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.users(id) on delete cascade,
    envelope jsonb not null,
    payload_b64 text not null,
    created_at timestamptz not null default now(),
    tags text[] not null default '{}'
);

create table if not exists public.memory_vectors (
    memory_id uuid primary key references public.memories(id) on delete cascade,
    embedding vector(384) not null
);

create table if not exists public.subscriptions (
    user_id uuid primary key references public.users(id) on delete cascade,
    status text not null,
    current_period_end timestamptz,
    stripe_customer_id text,
    stripe_subscription_id text,
    plan_code text not null,
    unit_price_cents int not null,
    agent_quota int not null,
    storage_cap_bytes bigint not null
);

create table if not exists public.agent_tokens (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.users(id) on delete cascade,
    token_hash text not null unique,
    name text not null,
    created_at timestamptz not null default now(),
    revoked_at timestamptz
);

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

-- Managed wrapped key custody (P4.4):
-- - plaintext data_key never leaves the client
-- - edge function `vault-custody` handles sealed box operations through pgsodium RPC
-- - table stores only wrapped key material scoped by auth.uid()
create table if not exists public.vault_keys (
    user_id uuid primary key references public.users(id) on delete cascade,
    wrapped_key bytea not null,
    kdf_salt bytea not null,
    algo text not null default 'aes-gcm',
    rotated_at timestamptz not null default now()
);

create index if not exists idx_memories_user_id_created_at on public.memories(user_id, created_at desc);
create index if not exists idx_memories_tags on public.memories using gin(tags);
create index if not exists idx_memory_vectors_embedding_ivfflat
    on public.memory_vectors
    using ivfflat (embedding vector_cosine_ops)
    with (lists = 100);
create index if not exists idx_agent_tokens_user_id_created_at on public.agent_tokens(user_id, created_at desc);
create index if not exists idx_agents_user_id_connected_at on public.agents(user_id, connected_at desc);

alter table public.users enable row level security;
alter table public.profiles enable row level security;
alter table public.memories enable row level security;
alter table public.memory_vectors enable row level security;
alter table public.subscriptions enable row level security;
alter table public.agent_tokens enable row level security;
alter table public.agents enable row level security;
alter table public.vault_keys enable row level security;

-- users: self-only access
create policy users_select_own on public.users
    for select using (id = auth.uid());
create policy users_insert_own on public.users
    for insert with check (id = auth.uid());
create policy users_update_own on public.users
    for update using (id = auth.uid()) with check (id = auth.uid());

-- profiles: user_id = auth.uid()
create policy profiles_select_own on public.profiles
    for select using (user_id = auth.uid());
create policy profiles_insert_own on public.profiles
    for insert with check (user_id = auth.uid());
create policy profiles_update_own on public.profiles
    for update using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy profiles_delete_own on public.profiles
    for delete using (user_id = auth.uid());

-- memories: user_id = auth.uid()
create policy memories_select_own on public.memories
    for select using (user_id = auth.uid());
create policy memories_insert_own on public.memories
    for insert with check (user_id = auth.uid());
create policy memories_update_own on public.memories
    for update using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy memories_delete_own on public.memories
    for delete using (user_id = auth.uid());

-- memory_vectors inherits owner scope through memories join
create policy memory_vectors_select_own on public.memory_vectors
    for select using (
        exists (
            select 1
            from public.memories m
            where m.id = memory_vectors.memory_id
              and m.user_id = auth.uid()
        )
    );
create policy memory_vectors_insert_own on public.memory_vectors
    for insert with check (
        exists (
            select 1
            from public.memories m
            where m.id = memory_vectors.memory_id
              and m.user_id = auth.uid()
        )
    );
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
create policy subscriptions_select_own on public.subscriptions
    for select using (user_id = auth.uid());
create policy subscriptions_insert_own on public.subscriptions
    for insert with check (user_id = auth.uid());
create policy subscriptions_update_own on public.subscriptions
    for update using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy subscriptions_delete_own on public.subscriptions
    for delete using (user_id = auth.uid());

-- agent_tokens: user_id = auth.uid()
create policy agent_tokens_select_own on public.agent_tokens
    for select using (user_id = auth.uid());
create policy agent_tokens_insert_own on public.agent_tokens
    for insert with check (user_id = auth.uid());
create policy agent_tokens_update_own on public.agent_tokens
    for update using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy agent_tokens_delete_own on public.agent_tokens
    for delete using (user_id = auth.uid());

-- agents: user_id = auth.uid()
create policy agents_select_own on public.agents
    for select using (user_id = auth.uid());
create policy agents_insert_own on public.agents
    for insert with check (user_id = auth.uid());
create policy agents_update_own on public.agents
    for update using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy agents_delete_own on public.agents
    for delete using (user_id = auth.uid());

-- vault_keys: user_id = auth.uid()
create policy vault_keys_select_own on public.vault_keys
    for select using (user_id = auth.uid());
create policy vault_keys_insert_own on public.vault_keys
    for insert with check (user_id = auth.uid());
create policy vault_keys_update_own on public.vault_keys
    for update using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy vault_keys_delete_own on public.vault_keys
    for delete using (user_id = auth.uid());

-- Edge function prerequisites for server custody operations:
--   1) create pgsodium-backed RPC `vault_seal_box(plaintext_b64 text)`.
--   2) create pgsodium-backed RPC `vault_open_box(sealed_b64 text)`.
--   3) edge function `vault-custody` calls these RPCs and writes only wrapped bytes here.
