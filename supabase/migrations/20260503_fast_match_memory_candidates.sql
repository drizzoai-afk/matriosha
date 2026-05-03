-- Fast managed keyed candidate retrieval for private top-k preselection.
-- Avoid per-row unnest scoring and only touch vectors when an embedding is supplied.

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
    with keyed_candidates as (
        select
            m.id,
            m.safe_metadata,
            m.tags,
            m.search_keywords,
            m.metadata_hashes,
            m.created_at,
            (coalesce(cardinality(p_metadata_hashes), 0) > 0 and m.metadata_hashes && p_metadata_hashes) as metadata_hash_match,
            (coalesce(cardinality(p_search_keywords), 0) > 0 and m.search_keywords && p_search_keywords) as keyword_match,
            (coalesce(cardinality(p_tags), 0) > 0 and m.tags && p_tags) as tag_match
        from public.memories m
        where m.user_id = p_user_id
          and (p_metadata_hashes is null or cardinality(p_metadata_hashes) = 0 or m.metadata_hashes && p_metadata_hashes)
          and (p_search_keywords is null or cardinality(p_search_keywords) = 0 or m.search_keywords && p_search_keywords)
          and (p_tags is null or cardinality(p_tags) = 0 or m.tags && p_tags)
        order by
            (
                case when (coalesce(cardinality(p_metadata_hashes), 0) > 0 and m.metadata_hashes && p_metadata_hashes) then 10.0 else 0.0 end
              + case when (coalesce(cardinality(p_search_keywords), 0) > 0 and m.search_keywords && p_search_keywords) then 2.0 else 0.0 end
              + case when (coalesce(cardinality(p_tags), 0) > 0 and m.tags && p_tags) then 1.0 else 0.0 end
            ) desc,
            m.created_at desc,
            m.id asc
        limit least(greatest(coalesce(p_limit, 50), 1), 200)
    ),
    scored_candidates as (
        select
            kc.id,
            kc.safe_metadata,
            kc.tags,
            kc.search_keywords,
            kc.metadata_hashes,
            kc.created_at,
            kc.metadata_hash_match,
            kc.keyword_match,
            kc.tag_match,
            case
                when p_embedding is not null and mv.embedding is not null then (1.0 - (mv.embedding <=> p_embedding))::double precision
                else (
                    case when kc.metadata_hash_match then 10.0 else 0.0 end
                  + case when kc.keyword_match then 2.0 else 0.0 end
                  + case when kc.tag_match then 1.0 else 0.0 end
                )::double precision
            end as score,
            case
                when p_embedding is not null and mv.embedding is not null then (mv.embedding <=> p_embedding)::double precision
                else null::double precision
            end as distance
        from keyed_candidates kc
        left join public.memory_vectors mv
          on p_embedding is not null
         and mv.memory_id = kc.id
    )
    select
        sc.id as id,
        sc.id as memory_id,
        sc.score,
        sc.distance,
        sc.safe_metadata,
        sc.tags,
        sc.search_keywords,
        sc.metadata_hashes,
        sc.created_at
    from scored_candidates sc
    order by
        case when p_embedding is not null then sc.distance else null end asc nulls last,
        case when p_embedding is null then sc.score else null end desc nulls last,
        sc.created_at desc,
        sc.id asc;
$$;

