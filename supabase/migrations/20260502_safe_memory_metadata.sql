alter table public.memories
    add column if not exists safe_metadata jsonb not null default '{}'::jsonb,
    add column if not exists search_keywords text[] not null default '{}',
    add column if not exists metadata_hashes text[] not null default '{}';

create index if not exists idx_memories_safe_metadata
    on public.memories using gin(safe_metadata jsonb_path_ops);

create index if not exists idx_memories_search_keywords
    on public.memories using gin(search_keywords);

create index if not exists idx_memories_metadata_hashes
    on public.memories using gin(metadata_hashes);

create or replace function public.match_memory_candidates(
    p_user_id uuid,
    p_embedding vector(384) default null,
    p_tags text[] default null,
    p_search_keywords text[] default null,
    p_metadata_hashes text[] default null,
    p_limit int default 50
)
returns table (
    id uuid,
    memory_id uuid,
    score double precision,
    distance double precision,
    safe_metadata jsonb,
    tags text[],
    search_keywords text[],
    metadata_hashes text[],
    created_at timestamptz
)
language sql
stable
security definer
set search_path = public
as $$
    select
        m.id as id,
        m.id as memory_id,
        case
            when p_embedding is null then null
            else (1.0 - (mv.embedding <=> p_embedding))::double precision
        end as score,
        case
            when p_embedding is null then null
            else (mv.embedding <=> p_embedding)::double precision
        end as distance,
        m.safe_metadata,
        m.tags,
        m.search_keywords,
        m.metadata_hashes,
        m.created_at
    from public.memories m
    left join public.memory_vectors mv on mv.memory_id = m.id
    where m.user_id = p_user_id
      and (p_embedding is null or mv.embedding is not null)
      and (p_tags is null or cardinality(p_tags) = 0 or m.tags && p_tags)
      and (p_search_keywords is null or cardinality(p_search_keywords) = 0 or m.search_keywords && p_search_keywords)
      and (p_metadata_hashes is null or cardinality(p_metadata_hashes) = 0 or m.metadata_hashes && p_metadata_hashes)
    order by
        case when p_embedding is null then null else mv.embedding <=> p_embedding end asc nulls last,
        m.created_at desc
    limit least(greatest(coalesce(p_limit, 50), 1), 200);
$$;
