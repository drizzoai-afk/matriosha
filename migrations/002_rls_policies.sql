-- Matriosha RLS Policies (P7)
-- Enforces Zero-Knowledge and Data Sovereignty

-- Enable RLS
alter table vaults enable row level security;
alter table key_escrow enable row level security;
alter table subscriptions enable row level security;
alter table memory_vectors enable row level security;

-- Vaults: Owner full access
create policy "Owner full access" on vaults for all
  using (auth.uid()::text = user_id)
  with check (auth.uid()::text = user_id);

-- Key Escrow: Read-only for owner, Write via Edge Function
create policy "Owner can read key shard" on key_escrow for select
  using (auth.uid()::text = user_id);

-- Subscriptions: Read-only for owner
create policy "Owner can view subscription" on subscriptions for select
  using (auth.uid()::text = user_id);

-- Memory Vectors: Owner full access
create policy "Owner full access to vectors" on memory_vectors for all
  using (auth.uid()::text = user_id)
  with check (auth.uid()::text = user_id);
