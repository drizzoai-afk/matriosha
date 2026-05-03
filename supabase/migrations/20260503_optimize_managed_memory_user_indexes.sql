-- Improve managed candidate query planning for memory-vector joins.

create index if not exists idx_memory_vectors_memory_id
    on public.memory_vectors(memory_id);
