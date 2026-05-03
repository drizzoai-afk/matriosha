-- Atomic managed storage usage increments for concurrent uploads.
create or replace function public.increment_storage_usage(
    p_user_id uuid,
    p_delta_bytes bigint
)
returns bigint
language plpgsql
security definer
set search_path = public
as $$
declare
    v_delta bigint := greatest(coalesce(p_delta_bytes, 0), 0);
    v_used bigint;
begin
    insert into public.quota_usage (
        user_id,
        storage_used_bytes,
        raw_storage_bytes,
        compressed_storage_bytes,
        index_storage_bytes,
        updated_at
    )
    values (
        p_user_id,
        v_delta,
        v_delta,
        0,
        0,
        now()
    )
    on conflict (user_id) do update
    set
        storage_used_bytes = public.quota_usage.storage_used_bytes + excluded.storage_used_bytes,
        raw_storage_bytes = public.quota_usage.raw_storage_bytes + excluded.raw_storage_bytes,
        updated_at = now()
    returning storage_used_bytes into v_used;

    update public.subscriptions
    set
        storage_used_bytes = coalesce(storage_used_bytes, 0) + v_delta,
        updated_at = now()
    where user_id = p_user_id;

    return v_used;
end;
$$;

comment on function public.increment_storage_usage(uuid, bigint)
is 'Atomically increments managed storage usage after successful memory uploads.';
