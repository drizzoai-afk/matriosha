#!/usr/bin/env python3
"""Local MIRACL-fixture retrieval performance benchmark.

Uses existing fixture JSONL files:
- memories: {"key", "text", "tags"}
- queries: {"query", "expected_key", "category"}

Measures:
- local encrypted envelope/write time
- keyword metadata indexing time
- vector indexing time
- keyword candidate lookup latency
- semantic rerank latency
- end-to-end search latency
- Keyword Recall@candidate_limit
- Final Hit@final_k
- MRR@final_k

This is a self-retrieval benchmark, not official MIRACL qrels evaluation.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
import os
import shutil
import statistics
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

os.environ.setdefault("MATRIOSHA_EMBEDDER", "hash")

from matriosha.core.binary_protocol import encode_envelope, envelope_to_json
from matriosha.core.config import DEFAULT_MANAGED_ENDPOINT, get_active_profile, load_config
from matriosha.core.managed.auth import TokenStore
from matriosha.core.managed.client import ManagedClient
from matriosha.core.search_terms import build_retrieval_index_text, extract_search_terms, keyed_search_tokens
from matriosha.core.storage_local import LocalStore
from matriosha.core.local_vectors import get_local_vector_index
from matriosha.core.retrieval_ranking import hybrid_retrieval_score, weighted_keyword_score
from matriosha.core.vectors import get_default_embedder


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    rank = (len(values) - 1) * p
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return values[low]
    return values[low] + (values[high] - values[low]) * (rank - low)


def summarize_ms(values: list[float]) -> dict[str, float]:
    return {
        "count": float(len(values)),
        "mean_ms": statistics.fmean(values) if values else 0.0,
        "p50_ms": percentile(values, 0.50),
        "p95_ms": percentile(values, 0.95),
        "max_ms": max(values) if values else 0.0,
    }


def keyword_candidates(store: LocalStore, query: str, data_key: bytes, limit: int) -> list[str]:
    terms = extract_search_terms(query, max_terms=96)
    query_hashes = set(keyed_search_tokens(terms, data_key))
    scored: list[tuple[int, str]] = []

    for memory_id, metadata in store.index_metadata().items():
        raw_hashes = metadata.get("metadata_hashes", [])
        if not isinstance(raw_hashes, list):
            continue
        memory_hashes = {str(item) for item in raw_hashes}
        overlap = len(query_hashes & memory_hashes)
        if overlap:
            scored.append((overlap, memory_id))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [memory_id for _score, memory_id in scored[:limit]]


def rerank(
    vector_index: Any,
    query: str,
    query_vector: np.ndarray,
    candidate_ids: list[str],
    final_k: int,
    text_by_id: dict[str, str],
    keyword_score_by_id: dict[str, float],
) -> list[str]:
    if not candidate_ids:
        return []

    semantic_ranked = dict(
        vector_index.search(
            query_vector,
            k=len(candidate_ids),
            candidate_ids=set(candidate_ids),
            entry_types={"memory"},
        )
    )
    scored = [
        (
            hybrid_retrieval_score(
                query=query,
                candidate_text=text_by_id.get(memory_id, ""),
                semantic_score=float(semantic_ranked.get(memory_id, 0.0)),
                keyword_score=keyword_score_by_id.get(memory_id, 0.0),
            ),
            memory_id,
        )
        for memory_id in candidate_ids
    ]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [memory_id for _score, memory_id in scored[:final_k]]


def group_key(memory_id: str) -> str:
    parts = memory_id.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0]
    return memory_id


def choose_queries(
    queries: list[dict[str, Any]],
    available_keys: set[str],
    max_queries: int | None,
) -> list[dict[str, Any]]:
    selected = [row for row in queries if str(row.get("expected_key", "")) in available_keys]
    if max_queries is not None:
        selected = selected[:max_queries]
    return selected


def resolve_managed_auth(profile_override: str | None, endpoint_override: str | None) -> tuple[str, str, str]:
    cfg = load_config()
    requested_profile = str(profile_override or "").strip() or None
    profile = get_active_profile(cfg, requested_profile)
    profile_name = requested_profile or str(getattr(profile, "name", "") or "default").strip()
    store = TokenStore(profile_name)
    payload = store.load() or {}

    endpoint = str(
        endpoint_override
        or payload.get("endpoint")
        or getattr(profile, "managed_endpoint", None)
        or DEFAULT_MANAGED_ENDPOINT
    ).rstrip("/")
    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise ValueError(
            f"no managed access token found for profile {profile_name}; "
            f"token_store={getattr(store, '_path', None)}; "
            f"payload_keys={sorted(payload.keys())}"
        )
    return profile_name, endpoint, token


async def managed_bulk_upload(
    *,
    profile_name: str,
    endpoint: str,
    token: str,
    items: list[dict[str, Any]],
    timeout_seconds: float,
) -> list[str]:
    async with ManagedClient(
        token=token,
        base_url=endpoint,
        managed_mode=False,
        profile_name=None,
        timeout_seconds=timeout_seconds,
    ) as client:
        return await client.upload_memories(items)


def run(args: argparse.Namespace) -> dict[str, Any]:
    memory_path = Path(args.memories)
    query_path = Path(args.queries)

    memories = read_jsonl(memory_path)
    queries_all = read_jsonl(query_path)

    if args.max_memories is not None:
        memories = memories[: args.max_memories]

    available_keys = {str(row["key"]) for row in memories}
    queries = choose_queries(queries_all, available_keys, args.max_queries)

    if not memories:
        raise ValueError("no memories loaded")
    if not queries:
        raise ValueError("no queries loaded with expected_key present in selected memories")

    managed_profile_name: str | None = None
    managed_endpoint: str | None = None
    managed_token: str | None = None
    if args.mode == "managed":
        managed_profile_name, managed_endpoint, managed_token = resolve_managed_auth(
            args.managed_profile,
            args.managed_endpoint,
        )

    temp_root = Path(tempfile.mkdtemp(prefix="matriosha-local-miracl-perf-"))
    old_xdg_data_home = os.environ.get("XDG_DATA_HOME")
    os.environ["XDG_DATA_HOME"] = str(temp_root / ".local" / "share")

    profile = f"local-miracl-perf-{int(time.time())}"
    data_key = os.urandom(32)

    try:
        store = LocalStore(profile, data_key=data_key)
        vector_index = get_local_vector_index(profile, data_key=data_key)
        embedder = get_default_embedder()

        local_write_latencies: list[float] = []
        metadata_latencies: list[float] = []
        vector_add_latencies: list[float] = []
        managed_upload_latencies: list[float] = []
        managed_key_to_id: dict[str, str] = {}
        managed_id_to_key: dict[str, str] = {}
        managed_upload_items: list[dict[str, Any]] = []
        local_index: dict[str, dict[str, object]] = store.index_metadata()

        t_local_write_total = time.perf_counter()

        for idx, row in enumerate(memories, start=1):
            key = str(row["key"])
            text = str(row["text"])
            tags = [str(tag) for tag in row.get("tags", [])]

            env, payload = encode_envelope(
                text.encode("utf-8"),
                data_key,
                mode="local",
                tags=tags,
                source="cli",
                mime_type="text/plain",
                content_kind="text",
            )
            env.memory_id = key

            t0 = time.perf_counter()
            store.put(env, payload, embedding=None, update_index=False)
            local_write_latencies.append((time.perf_counter() - t0) * 1000)

            t0 = time.perf_counter()
            retrieval_index_text = build_retrieval_index_text(text)
            terms = extract_search_terms(retrieval_index_text, tags, "text/plain", "text", max_terms=96)
            metadata_hashes = keyed_search_tokens(terms, data_key)
            entry = store._build_safe_metadata(env, tags)
            entry["metadata_hashes"] = metadata_hashes
            entry["search_keywords_count"] = len(terms)
            local_index[key] = entry
            metadata_latencies.append((time.perf_counter() - t0) * 1000)

            if args.mode == "managed":
                managed_upload_items.append(
                    {
                        "envelope": json.loads(envelope_to_json(env)),
                        "payload_b64": base64.b64encode(payload).decode("ascii"),
                        "embedding": None,
                        "metadata_hashes": metadata_hashes,
                    }
                )

            if idx % args.progress_every == 0:
                print(f"[progress] wrote/indexed metadata {idx}/{len(memories)}", flush=True)

        t0 = time.perf_counter()
        store._write_index_atomic(local_index)
        metadata_index_save_ms = (time.perf_counter() - t0) * 1000

        local_write_total_ms = (time.perf_counter() - t_local_write_total) * 1000

        managed_upload_total_ms = 0.0
        if args.mode == "managed":
            if managed_profile_name is None or managed_endpoint is None or managed_token is None:
                raise RuntimeError("managed auth was not initialized")
            for start in range(0, len(managed_upload_items), args.managed_batch_size):
                batch = managed_upload_items[start : start + args.managed_batch_size]
                t0 = time.perf_counter()
                returned_ids = asyncio.run(
                    managed_bulk_upload(
                        profile_name=managed_profile_name,
                        endpoint=managed_endpoint,
                        token=managed_token,
                        items=batch,
                        timeout_seconds=args.managed_upload_timeout,
                    )
                )
                elapsed_ms = (time.perf_counter() - t0) * 1000
                managed_upload_total_ms += elapsed_ms
                per_item_ms = elapsed_ms / max(len(batch), 1)
                managed_upload_latencies.extend([per_item_ms] * len(batch))
                for item, managed_id in zip(batch, returned_ids, strict=True):
                    key = str(item["envelope"]["memory_id"])
                    managed_key_to_id[key] = managed_id
                    managed_id_to_key[managed_id] = key
                uploaded = min(start + len(batch), len(managed_upload_items))
                if uploaded % args.progress_every == 0 or uploaded == len(managed_upload_items):
                    print(f"[progress] uploaded managed memories {uploaded}/{len(managed_upload_items)}", flush=True)

        t_vector_total = time.perf_counter()
        for idx, row in enumerate(memories, start=1):
            key = str(row["key"])
            text = str(row["text"])

            t0 = time.perf_counter()
            embedding = np.asarray(embedder.embed(text[:4096]), dtype=np.float32)
            vector_index.add(key, embedding, entry_type="memory", is_active=True)
            vector_add_latencies.append((time.perf_counter() - t0) * 1000)

            if idx % args.progress_every == 0:
                print(f"[progress] built vectors {idx}/{len(memories)}", flush=True)

        t0 = time.perf_counter()
        vector_index.save()
        vector_save_ms = (time.perf_counter() - t0) * 1000
        vector_total_ms = (time.perf_counter() - t_vector_total) * 1000

        keyword_latencies: list[float] = []
        rerank_latencies: list[float] = []
        e2e_latencies: list[float] = []
        keyword_hits = 0
        keyword_group_hits = 0
        final_hits = 0
        final_group_hits = 0
        reciprocal_ranks: list[float] = []
        group_reciprocal_ranks: list[float] = []
        text_by_id = {str(row["key"]): str(row["text"]) for row in memories}
        query_diagnostics: list[dict[str, object]] = []
        metadata = store.index_metadata()

        for idx, row in enumerate(queries, start=1):
            query = str(row["query"])
            expected_key = str(row["expected_key"])

            t_e2e = time.perf_counter()

            t0 = time.perf_counter()
            query_terms = extract_search_terms(query, max_terms=96)
            query_hashes = keyed_search_tokens(query_terms, data_key)
            candidates = keyword_candidates(store, query, data_key, args.candidate_limit)
            keyword_score_by_id = {}
            for memory_id in candidates:
                candidate_hashes_value = metadata.get(memory_id, {}).get("metadata_hashes", [])
                candidate_hashes = candidate_hashes_value if isinstance(candidate_hashes_value, list) else []
                keyword_score_by_id[memory_id] = weighted_keyword_score(query_hashes, candidate_hashes)
            keyword_latencies.append((time.perf_counter() - t0) * 1000)

            expected_group = group_key(expected_key)
            candidate_groups = [group_key(memory_id) for memory_id in candidates]

            if expected_key in candidates:
                keyword_hits += 1
            if expected_group in candidate_groups:
                keyword_group_hits += 1

            t0 = time.perf_counter()
            query_vector = np.asarray(embedder.embed(query), dtype=np.float32)
            final_ids = rerank(
                vector_index,
                query,
                query_vector,
                candidates,
                args.final_k,
                text_by_id,
                keyword_score_by_id,
            )
            rerank_latencies.append((time.perf_counter() - t0) * 1000)
            final_groups = [group_key(memory_id) for memory_id in final_ids]

            if expected_key in final_ids:
                final_hits += 1
                reciprocal_ranks.append(1.0 / (final_ids.index(expected_key) + 1))
            else:
                reciprocal_ranks.append(0.0)

            if expected_group in final_groups:
                final_group_hits += 1
                group_reciprocal_ranks.append(1.0 / (final_groups.index(expected_group) + 1))
            else:
                group_reciprocal_ranks.append(0.0)

            if len(query_diagnostics) < 25 and expected_key not in final_ids:
                query_diagnostics.append(
                    {
                        "query": query,
                        "expected_key": expected_key,
                        "expected_in_candidates": expected_key in candidates,
                        "expected_group_in_candidates": expected_group in candidate_groups,
                        "expected_candidate_rank": candidates.index(expected_key) + 1 if expected_key in candidates else None,
                        "expected_group_candidate_rank": candidate_groups.index(expected_group) + 1
                        if expected_group in candidate_groups
                        else None,
                        "expected_keyword_score": keyword_score_by_id.get(expected_key),
                        "final_ids": final_ids,
                        "final_groups": final_groups,
                        "expected_text": text_by_id.get(expected_key, "")[:500],
                    }
                )

            e2e_latencies.append((time.perf_counter() - t_e2e) * 1000)

            if idx % args.progress_every == 0:
                print(f"[progress] searched {idx}/{len(queries)}", flush=True)

        n = len(queries)
        result = {
            "benchmark": "local_miracl_fixture_performance",
            "created_at": datetime.now(UTC).isoformat(),
            "fixture": {
                "memories": str(memory_path),
                "queries": str(query_path),
            },
            "mode": args.mode,
            "profile": managed_profile_name if args.mode == "managed" else profile,
            "managed_endpoint": managed_endpoint if args.mode == "managed" else None,
            "memory_count": len(memories),
            "query_count": n,
            "candidate_limit": args.candidate_limit,
            "final_k": args.final_k,
            "quality": {
                f"keyword_recall_at_{args.candidate_limit}": keyword_hits / n,
                f"keyword_group_recall_at_{args.candidate_limit}": keyword_group_hits / n,
                f"final_hit_at_{args.final_k}": final_hits / n,
                f"final_group_hit_at_{args.final_k}": final_group_hits / n,
                f"mrr_at_{args.final_k}": statistics.fmean(reciprocal_ranks),
                f"group_mrr_at_{args.final_k}": statistics.fmean(group_reciprocal_ranks),
            },
            "diagnostics": {
                "sample_final_misses": query_diagnostics,
            },
            "latency_ms": {
                "local_write_per_memory": summarize_ms(local_write_latencies),
                "metadata_index_per_memory": summarize_ms(metadata_latencies),
                "vector_add_per_memory": summarize_ms(vector_add_latencies),
                "managed_upload_per_memory": summarize_ms(managed_upload_latencies),
                "keyword_candidates": summarize_ms(keyword_latencies),
                "semantic_rerank": summarize_ms(rerank_latencies),
                "search_e2e": summarize_ms(e2e_latencies),
            },
            "totals_ms": {
                "local_write_and_metadata_total": local_write_total_ms,
                "metadata_index_save": metadata_index_save_ms,
                "vector_total": vector_total_ms,
                "vector_save": vector_save_ms,
                "managed_upload_total": managed_upload_total_ms,
            },
        }

        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%S.%fZ")
        output_path = output_dir / f"local_miracl_performance_{stamp}.json"
        output_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        result["output_path"] = str(output_path)

        return result

    finally:
        if old_xdg_data_home is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = old_xdg_data_home
        if not args.keep_temp:
            shutil.rmtree(temp_root, ignore_errors=True)


def print_rows(result: dict[str, Any]) -> None:
    print()
    print("metric,value")
    print(f"benchmark,{result['benchmark']}")
    print(f"mode,{result['mode']}")
    print(f"memory_count,{result['memory_count']}")
    print(f"query_count,{result['query_count']}")
    print(f"candidate_limit,{result['candidate_limit']}")
    print(f"final_k,{result['final_k']}")
    for key, value in result["quality"].items():
        print(f"{key},{value:.6f}")
    for key, value in result["totals_ms"].items():
        print(f"{key},{value:.3f}")
    for group, stats in result["latency_ms"].items():
        for key, value in stats.items():
            print(f"{group}_{key},{value:.3f}")
    print(f"output_path,{result['output_path']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--memories", default="benchmarks/fixtures/miracl_self_exact_600_memories.jsonl")
    parser.add_argument("--queries", default="benchmarks/fixtures/miracl_self_exact_600_queries.jsonl")
    parser.add_argument("--max-memories", type=int, default=None)
    parser.add_argument("--max-queries", type=int, default=None)
    parser.add_argument("--mode", choices=["local"], default="local")
    parser.add_argument("--managed-profile", default=None)
    parser.add_argument("--managed-endpoint", default=None)
    parser.add_argument("--managed-batch-size", type=int, default=10)
    parser.add_argument("--managed-upload-timeout", type=float, default=30.0)
    parser.add_argument("--candidate-limit", type=int, default=50)
    parser.add_argument("--final-k", type=int, default=5)
    parser.add_argument("--output-dir", default="benchmarks/results")
    parser.add_argument("--progress-every", type=int, default=500)
    parser.add_argument("--keep-temp", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--rows", action="store_true")
    args = parser.parse_args()

    result = run(args)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    if args.rows or not args.json:
        print_rows(result)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
