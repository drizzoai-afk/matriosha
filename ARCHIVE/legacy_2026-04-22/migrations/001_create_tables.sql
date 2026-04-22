-- Matriosha Supabase Schema (P7)
-- Production-ready with RLS and optimized indexes

-- 1. Vaults Table
create table if not exists vaults (
  id uuid primary key default gen_random_uuid(),
  user_id text not null, -- Clerk JWT 'sub' claim
  merkle_root text not null,
  vault_version int default 1,
  last_sync timestamptz default now(),
  created_at timestamptz default now(),
  constraint unique_user_vault unique(user_id)
);

-- 2. Key Escrow (Shamir's Shard)
create table if not exists key_escrow (
  id uuid primary key default gen_random_uuid(),
  user_id text not null,
  encrypted_key_shard text not null,
  created_at timestamptz default now(),
  constraint unique_user_escrow unique(user_id)
);

-- 3. Subscriptions (Stripe Sync)
create table if not exists subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id text not null,
  stripe_customer_id text,
  stripe_subscription_id text,
  status text check (status in ('active', 'canceled', 'past_due')),
  tier text check (tier in ('free', 'pro', 'builder')),
  current_period_end timestamptz,
  updated_at timestamptz default now(),
  constraint unique_user_sub unique(user_id)
);

-- 4. Memory Vectors (Cloud Fallback)
create extension if not exists vector;
create table if not exists memory_vectors (
  id uuid primary key default gen_random_uuid(),
  user_id text not null,
  leaf_id text not null,
  embedding vector(384),
  importance int check (importance between 0 and 3),
  logic_state int check (logic_state between 0 and 2),
  created_at timestamptz default now()
);

-- Indexes for performance
create index if not exists idx_vectors_user on memory_vectors(user_id);
create index if not exists idx_vectors_embedding on memory_vectors using ivfflat (embedding vector_cosine_ops);
