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
    with candidates as (
        select
            m.id,
            m.safe_metadata,
            m.tags,
            m.search_keywords,
            m.metadata_hashes,
            m.created_at,
            mv.embedding,
            (
                select count(*)::double precision
                from unnest(m.tags) as tag
                where tag = any(coalesce(p_tags, '{}'::text[]))
            ) as tag_matches,
            (
                select count(*)::double precision
                from unnest(m.search_keywords) as keyword
                where keyword = any(coalesce(p_search_keywords, '{}'::text[]))
            ) as keyword_matches,
            (
                select count(*)::double precision
                from unnest(m.metadata_hashes) as metadata_hash
                where metadata_hash = any(coalesce(p_metadata_hashes, '{}'::text[]))
            ) as metadata_hash_matches
        from public.memories m
        left join public.memory_vectors mv on mv.memory_id = m.id
        where m.user_id = p_user_id
          and (p_tags is null or cardinality(p_tags) = 0 or m.tags && p_tags)
          and (p_search_keywords is null or cardinality(p_search_keywords) = 0 or m.search_keywords && p_search_keywords)
          and (p_metadata_hashes is null or cardinality(p_metadata_hashes) = 0 or m.metadata_hashes && p_metadata_hashes)
    )
    select
        c.id as id,
        c.id as memory_id,
        case
            when p_embedding is not null and c.embedding is not null then (1.0 - (c.embedding <=> p_embedding))::double precision
            else (c.metadata_hash_matches * 10.0 + c.keyword_matches * 2.0 + c.tag_matches)::double precision
        end as score,
        case
            when p_embedding is not null and c.embedding is not null then (c.embedding <=> p_embedding)::double precision
            else null
        end as distance,
        c.safe_metadata,
        c.tags,
        c.search_keywords,
        c.metadata_hashes,
        c.created_at
    from candidates c
    order by
        (c.metadata_hash_matches * 10.0 + c.keyword_matches * 2.0 + c.tag_matches) desc,
        case
            when p_embedding is not null and c.embedding is not null then c.embedding <=> p_embedding
            else null
        end asc nulls last,
        c.created_at desc
    limit least(greatest(coalesce(p_limit, 50), 1), 200);
$$;
