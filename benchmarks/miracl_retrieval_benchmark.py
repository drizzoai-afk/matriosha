#!/usr/bin/env python3
"""MIRACL-backed retrieval benchmark for Matriosha local retrieval.

This benchmark uses public MIRACL topics, qrels, and corpus passages.
It indexes MIRACL corpus passages as Matriosha memories, searches with MIRACL
queries, and evaluates whether any positive qrel document is retrieved.

This is not an official MIRACL leaderboard submission. It is a Matriosha
retrieval benchmark derived from MIRACL data.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import os
import random
import re
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from huggingface_hub import hf_hub_download, list_repo_files

from matriosha.core.binary_protocol import decode_envelope, encode_envelope, envelope_from_json
from matriosha.core.config import MatrioshaConfig, Profile, get_active_profile, load_config, save_config
from matriosha.core.search_terms import build_retrieval_index_text, extract_search_terms, keyed_search_tokens
from matriosha.core.managed.auth import resolve_access_token
from matriosha.core.managed.client import ManagedClient
from matriosha.core.storage_local import LocalStore
from matriosha.core.vault import Vault
from matriosha.core.vectors import LocalVectorIndex, get_default_embedder


CANDIDATE_LIMIT = 50
FINAL_K = 5


@dataclass(frozen=True)
class MiraclQuery:
    language: str
    query_id: str
    query: str
    positive_docids: tuple[str, ...]


@dataclass(frozen=True)
class MiraclDoc:
    language: str
    docid: str
    title: str
    text: str


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1))))
    return ordered[idx]


def setup_temp_profile(profile: str, root: Path) -> bytes:
    config_root = root / ".config" / "matriosha"
    data_root = root / ".local" / "share" / "matriosha"
    sync_root = root / "sync"

    import matriosha.core.config as config_module
    import matriosha.core.vault as vault_module
    import matriosha.core.storage_local as store_module
    import matriosha.core.vectors as vectors_module

    config_module.platformdirs.user_config_dir = lambda appname: str(config_root)
    vault_module.platformdirs.user_data_dir = lambda appname: str(data_root)
    store_module.platformdirs.user_data_dir = lambda appname: str(data_root)
    vectors_module.platformdirs.user_data_dir = lambda appname: str(data_root)

    cfg = MatrioshaConfig(
        active_profile=profile,
        profiles={
            profile: Profile(
                name=profile,
                mode="local",
                sync_dir=str(sync_root),
            )
        },
    )
    save_config(cfg)
    vault = Vault.init(profile, "benchmark-passphrase", force=True)
    return vault.data_key


def setup_persistent_profile(profile: str) -> bytes:
    try:
        vault = Vault.unlock(profile, "benchmark-passphrase")
    except Exception:
        cfg = load_config()
        profiles = dict(cfg.profiles)
        profiles[profile] = Profile(
            name=profile,
            mode="local",
            sync_dir=None,
        )
        save_config(MatrioshaConfig(active_profile=profile, profiles=profiles))
        vault = Vault.init(profile, "benchmark-passphrase", force=False)
    return vault.data_key


def load_topics(lang: str, split: str) -> dict[str, str]:
    filename = f"miracl-v1.0-{lang}/topics/topics.miracl-v1.0-{lang}-{split}.tsv"
    local = hf_hub_download(repo_id="miracl/miracl", repo_type="dataset", filename=filename)
    topics: dict[str, str] = {}
    with open(local, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line:
                continue
            query_id, query = line.split("\t", 1)
            topics[query_id] = query
    return topics


def load_qrels(lang: str, split: str) -> dict[str, list[str]]:
    filename = f"miracl-v1.0-{lang}/qrels/qrels.miracl-v1.0-{lang}-{split}.tsv"
    local = hf_hub_download(repo_id="miracl/miracl", repo_type="dataset", filename=filename)
    positives: dict[str, list[str]] = defaultdict(list)
    with open(local, "r", encoding="utf-8") as handle:
        for line in handle:
            parts = line.strip().split()
            if len(parts) != 4:
                continue
            query_id, _q0, docid, relevance = parts
            try:
                rel = int(relevance)
            except ValueError:
                continue
            if rel > 0:
                positives[query_id].append(docid)
    return positives


def shard_num(path: str) -> int:
    name = Path(path).name
    return int(name.removeprefix("docs-").removesuffix(".jsonl.gz"))


def list_corpus_shards(lang: str) -> list[str]:
    prefix = f"miracl-corpus-v1.0-{lang}/docs-"
    files = list_repo_files("miracl/miracl-corpus", repo_type="dataset")
    shards = [
        file for file in files
        if file.startswith(prefix) and file.endswith(".jsonl.gz")
    ]
    return sorted(shards, key=shard_num)


def select_queries(
    lang: str,
    split: str,
    queries_per_language: int,
    seed: int,
) -> list[MiraclQuery]:
    topics = load_topics(lang, split)
    positives = load_qrels(lang, split)
    eligible = [
        MiraclQuery(lang, query_id, topics[query_id], tuple(docids))
        for query_id, docids in positives.items()
        if query_id in topics and docids
    ]
    if not eligible:
        raise ValueError(f"No eligible MIRACL queries for {lang}/{split}")

    rng = random.Random(seed + sum(ord(ch) for ch in lang))
    rng.shuffle(eligible)
    return eligible[:queries_per_language]


def collect_docs_from_first_shards(
    lang: str,
    *,
    max_docs: int,
    max_shards: int,
) -> dict[str, MiraclDoc]:
    docs: dict[str, MiraclDoc] = {}
    files = sorted(list_repo_files("miracl/miracl-corpus", repo_type="dataset"))
    shard_files = [
        f for f in files
        if f.startswith(f"miracl-corpus-v1.0-{lang}/") and f.endswith(".jsonl.gz")
    ]
    shard_files.sort(key=shard_num)

    for shard in shard_files[:max_shards]:
        local = hf_hub_download(repo_id="miracl/miracl-corpus", repo_type="dataset", filename=shard)
        with gzip.open(local, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                docid = str(row.get("docid") or row.get("_id") or row.get("id"))
                title = str(row.get("title") or "")
                body = str(row.get("text") or row.get("contents") or "")
                docs[docid] = MiraclDoc(language=lang, docid=docid, title=title, text=body)
                if len(docs) >= max_docs:
                    return docs
    return docs


def select_queries_from_available_docs(
    lang: str,
    split: str,
    queries_per_language: int,
    seed: int,
    available_docids: set[str],
) -> list[MiraclQuery]:
    topics = load_topics(lang, split)
    qrels = load_qrels(lang, split)
    candidates = [
        MiraclQuery(
            language=lang,
            query_id=query_id,
            query=topics[query_id],
            positive_docids=tuple(docid for docid in positives if docid in available_docids),
        )
        for query_id, positives in qrels.items()
        if query_id in topics and any(docid in available_docids for docid in positives)
    ]
    rng = random.Random(seed)
    rng.shuffle(candidates)
    selected = candidates[:queries_per_language]
    if len(selected) < queries_per_language:
        raise ValueError(
            f"Only found {len(selected)} {lang} queries with positives in first scanned shards; "
            f"increase --max-shards-per-language or --distractors-per-language"
        )
    return selected


def collect_docs_for_queries(
    lang: str,
    queries: list[MiraclQuery],
    distractors: int,
    seed: int,
    max_shards: int | None,
) -> dict[str, MiraclDoc]:
    required_docids = {docid for query in queries for docid in query.positive_docids}
    docs: dict[str, MiraclDoc] = {}
    distractor_count = 0
    rng = random.Random(seed + 1009 + sum(ord(ch) for ch in lang))
    distractor_keep_probability = 0.08

    shards = list_corpus_shards(lang)
    if not shards:
        raise ValueError(f"No MIRACL corpus shards found for language {lang}")

    scanned = 0
    for shard in shards:
        if max_shards is not None and scanned >= max_shards:
            break
        scanned += 1
        local = hf_hub_download(
            repo_id="miracl/miracl-corpus",
            repo_type="dataset",
            filename=shard,
        )
        with gzip.open(local, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                docid = row.get("docid")
                if not isinstance(docid, str) or docid in docs:
                    continue

                should_keep = False
                if docid in required_docids:
                    should_keep = True
                elif distractor_count < distractors and rng.random() < distractor_keep_probability:
                    should_keep = True
                    distractor_count += 1

                if should_keep:
                    docs[docid] = MiraclDoc(
                        language=lang,
                        docid=docid,
                        title=str(row.get("title") or ""),
                        text=str(row.get("text") or ""),
                    )

                if required_docids.issubset(docs.keys()) and distractor_count >= distractors:
                    return docs

    missing = sorted(required_docids - set(docs))
    if missing:
        print(
            f"[warning] {lang}: missing {len(missing)} required MIRACL positive docs after scanning "
            f"{scanned} shards; first missing: {missing[:10]}. "
            "Queries without any indexed positive doc will be filtered before evaluation."
        )
    return docs


def memory_id_for_doc(lang: str, docid: str) -> str:
    safe_docid = re.sub(r"[^A-Za-z0-9_.:-]", "_", docid)
    return f"miracl::{lang}::{safe_docid}"[:128]


def index_docs(profile: str, data_key: bytes, docs: list[MiraclDoc]) -> tuple[LocalStore, LocalVectorIndex, dict[str, str]]:
    store = LocalStore(profile)
    vector_index = LocalVectorIndex(profile)
    embedder = get_default_embedder()
    doc_to_memory_id: dict[str, str] = {}
    items: list[tuple[Any, str, np.ndarray, list[bytes]]] = []

    for doc in docs:
        memory_text = f"{doc.title}\n\n{doc.text}".strip()
        memory_id = memory_id_for_doc(doc.language, doc.docid)
        try:
            store.get(memory_id)
        except FileNotFoundError:
            pass
        else:
            doc_to_memory_id[f"{doc.language}:{doc.docid}"] = memory_id
            continue

        env, b64_payload = encode_envelope(
            memory_text.encode("utf-8"),
            data_key,
            mode="local",
            tags=[f"miracl:{doc.language}", "miracl"],
            source="cli",
            mime_type="text/plain",
            content_kind="text",
        )
        env.memory_id = memory_id
        retrieval_index_text = build_retrieval_index_text(memory_text)
        terms = extract_search_terms(
            retrieval_index_text,
            (f"miracl:{doc.language}", "miracl"),
            "text/plain",
            "text",
        )
        tokens = keyed_search_tokens(terms, data_key)
        embedding = np.asarray(embedder.embed(memory_text[:4096]), dtype=np.float32)
        items.append((env, b64_payload, embedding, tokens))
        doc_to_memory_id[f"{doc.language}:{doc.docid}"] = memory_id

    store.bulk_upsert_with_search_tokens(
        [(env, payload, tokens) for env, payload, _embedding, tokens in items]
    )
    vector_index.upsert_many([(env.memory_id, embedding) for env, _payload, embedding, _tokens in items])
    return store, vector_index, doc_to_memory_id


async def index_docs_managed(
    client: ManagedClient,
    data_key: bytes,
    docs: list[MiraclDoc],
) -> dict[str, str]:
    embedder = get_default_embedder()
    doc_to_memory_id: dict[str, str] = {}

    for doc in docs:
        memory_text = f"{doc.title}\n\n{doc.text}".strip()
        memory_id = memory_id_for_doc(doc.language, doc.docid)

        env, b64_payload = encode_envelope(
            memory_text.encode("utf-8"),
            data_key,
            mode="managed",
            tags=[f"miracl:{doc.language}", "miracl"],
            source="cli",
            mime_type="text/plain",
            content_kind="text",
        )
        env.memory_id = memory_id
        retrieval_index_text = build_retrieval_index_text(memory_text)
        terms = extract_search_terms(
            retrieval_index_text,
            (f"miracl:{doc.language}", "miracl"),
            "text/plain",
            "text",
        )
        tokens = keyed_search_tokens(terms, data_key)
        embedding = [float(value) for value in embedder.embed(memory_text[:4096])]
        uploaded_id = await client.upload_memory(
            json.loads(env.to_json()),
            b64_payload,
            embedding,
            metadata_hashes=tokens,
        )
        doc_to_memory_id[f"{doc.language}:{doc.docid}"] = uploaded_id or memory_id

    return doc_to_memory_id


async def search_once_managed(
    client: ManagedClient,
    embedder: Any,
    data_key: bytes,
    query: str,
    candidate_limit: int,
    final_k: int,
) -> tuple[list[str], list[str], dict[str, float | int]]:
    timings: dict[str, float | int] = {}

    t0 = time.perf_counter()
    terms = extract_search_terms(query, (), "text/plain", "text")
    tokens = keyed_search_tokens(terms, data_key)
    candidate_rows = await client.search_candidates(
        k=candidate_limit,
        metadata_hashes=tokens,
    )
    timings["terms_ms"] = 0.0
    timings["candidate_ms"] = (time.perf_counter() - t0) * 1000

    candidate_ids: list[str] = []
    scored_rows: list[tuple[str, float]] = []
    query_vec = embedder.embed(query)

    t1 = time.perf_counter()
    for item in candidate_rows:
        memory_id = str(item.get("memory_id") or item.get("id") or "")
        if not memory_id:
            continue
        candidate_ids.append(memory_id)

        env_data = item.get("envelope") or item.get("metadata") or item
        payload_b64 = str(item.get("payload_b64") or item.get("payload") or "")
        if not payload_b64:
            continue

        try:
            env_json = env_data if isinstance(env_data, str) else json.dumps(env_data)
            env = envelope_from_json(env_json)
            plaintext = decode_envelope(env, payload_b64.encode("ascii"), data_key)
            text = plaintext.decode("utf-8", errors="replace")
            rerank_vec = embedder.embed(text[:4096])
            score = float(np.dot(query_vec, rerank_vec) / ((np.linalg.norm(query_vec) * np.linalg.norm(rerank_vec)) or 1.0))
            scored_rows.append((memory_id, score))
        except Exception:
            continue

    timings["rerank_ms"] = (time.perf_counter() - t1) * 1000
    ranked = [
        memory_id
        for memory_id, _score in sorted(scored_rows, key=lambda row: row[1], reverse=True)[:final_k]
    ]
    timings["candidate_count"] = len(candidate_ids)
    timings["total_ms"] = (time.perf_counter() - t0) * 1000
    return ranked, candidate_ids, timings


def search_once(
    store: LocalStore,
    vector_index: LocalVectorIndex,
    embedder: Any,
    data_key: bytes,
    query: str,
    candidate_limit: int,
    final_k: int,
) -> tuple[list[str], list[str], dict[str, float | int]]:
    timings: dict[str, float | int] = {}

    t0 = time.perf_counter()
    terms = extract_search_terms(query, (), "text/plain", "text")
    query_tokens = keyed_search_tokens(terms, data_key)
    timings["terms_ms"] = (time.perf_counter() - t0) * 1000

    t1 = time.perf_counter()
    candidate_ids = store.search_candidate_ids_by_tokens(query_tokens, limit=candidate_limit)
    timings["candidate_ms"] = (time.perf_counter() - t1) * 1000
    timings["candidate_count"] = len(candidate_ids)

    t2 = time.perf_counter()
    query_embedding = np.asarray(embedder.embed(query), dtype=np.float32)
    vector_hits = vector_index.search(query_embedding, k=final_k, candidate_ids=candidate_ids)
    timings["rerank_ms"] = (time.perf_counter() - t2) * 1000
    timings["total_ms"] = timings["terms_ms"] + timings["candidate_ms"] + timings["rerank_ms"]

    return [memory_id for memory_id, _score in vector_hits], candidate_ids, timings


def summarize_rows(rows: list[dict[str, Any]], candidate_limit: int, final_k: int) -> dict[str, Any]:
    n = len(rows)
    total_latencies = [float(row["total_ms"]) for row in rows]
    term_latencies = [float(row["terms_ms"]) for row in rows]
    candidate_latencies = [float(row["candidate_ms"]) for row in rows]
    rerank_latencies = [float(row["rerank_ms"]) for row in rows]
    candidate_counts = [int(row["candidate_count"]) for row in rows]

    hit1 = sum(1 for row in rows if row["rank"] == 1)
    hit5 = sum(1 for row in rows if row["rank"] is not None and row["rank"] <= 5)
    keyword = sum(1 for row in rows if row["keyword_recall_at_50"])
    mrr = sum((1.0 / row["rank"]) if row["rank"] else 0.0 for row in rows) / n

    return {
        "queries": n,
        "candidate_limit": candidate_limit,
        "final_k": final_k,
        "keyword_recall_at_50": round(keyword / n, 4),
        "hit_at_1": round(hit1 / n, 4),
        "hit_at_5": round(hit5 / n, 4),
        "mrr": round(mrr, 4),
        "latency_total_p50_ms": round(percentile(total_latencies, 50), 2),
        "latency_total_p95_ms": round(percentile(total_latencies, 95), 2),
        "latency_terms_p50_ms": round(percentile(term_latencies, 50), 2),
        "latency_candidate_p50_ms": round(percentile(candidate_latencies, 50), 2),
        "latency_rerank_p50_ms": round(percentile(rerank_latencies, 50), 2),
        "candidate_count_p50": percentile(candidate_counts, 50),
        "candidate_count_p95": percentile(candidate_counts, 95),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--languages", nargs="+", required=True)
    parser.add_argument("--split", default="dev")
    parser.add_argument("--queries-per-language", type=int, default=25)
    parser.add_argument("--distractors-per-language", type=int, default=500)
    parser.add_argument(
        "--query-source",
        choices=("selected-positives", "available-docs"),
        default="selected-positives",
        help=(
            "selected-positives selects MIRACL qrels first and scans corpus shards to find positive docs. "
            "available-docs samples available corpus docs first, then selects only MIRACL queries whose positive docs are present."
        ),
    )
    parser.add_argument(
        "--max-shards-per-language",
        type=int,
        default=None,
        help="Optional maximum MIRACL corpus shards to scan per language while fetching selected query positives.",
    )
    parser.add_argument(
        "--mode",
        choices=("local", "managed"),
        default="local",
        help="Benchmark local retrieval or managed keyword-candidate retrieval with local rerank.",
    )
    parser.add_argument(
        "--managed-profile",
        default=None,
        help="Managed profile name to use when --mode managed. Defaults to active profile.",
    )
    parser.add_argument(
        "--managed-endpoint",
        default=None,
        help="Optional managed API endpoint override for --mode managed.",
    )
    parser.add_argument(
        "--persistent-profile",
        default=None,
        help="Use a persistent local benchmark profile instead of a temporary profile.",
    )
    parser.add_argument(
        "--distractor-scales",
        nargs="+",
        type=int,
        default=None,
        help="Optional scale tiers for distractors per language, e.g. 100 500 2000 10000.",
    )
    parser.add_argument("--candidate-limit", type=int, default=CANDIDATE_LIMIT)
    parser.add_argument("--final-k", type=int, default=FINAL_K)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", default="benchmarks/results")
    parser.add_argument("--rows", action="store_true")
    args = parser.parse_args()

    os.environ.setdefault("MATRIOSHA_EMBEDDER", "hash")

    started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    distractor_scales = args.distractor_scales or [args.distractors_per_language]
    distractor_scales = sorted(set(distractor_scales))

    all_queries: list[MiraclQuery] = []
    required_by_lang: dict[str, set[str]] = {}

    max_distractors = max(distractor_scales)
    max_docs_by_lang: dict[str, dict[str, MiraclDoc]] = {}
    queries_by_lang: dict[str, list[MiraclQuery]] = {}
    for lang in args.languages:
        if args.query_source == "available-docs":
            first_pass_docs = collect_docs_from_first_shards(
                lang,
                max_docs=max_distractors + args.queries_per_language * 20,
                max_shards=args.max_shards_per_language or 1,
            )
            queries = select_queries_from_available_docs(
                lang,
                args.split,
                args.queries_per_language,
                args.seed,
                set(first_pass_docs),
            )
            required_docids = {docid for query in queries for docid in query.positive_docids}
            required_docs = {
                docid: doc for docid, doc in first_pass_docs.items() if docid in required_docids
            }
            distractor_docs = {
                docid: doc for docid, doc in first_pass_docs.items() if docid not in required_docids
            }
            max_docs_by_lang[lang] = {**required_docs, **dict(list(distractor_docs.items())[:max_distractors])}
        else:
            queries = select_queries(lang, args.split, args.queries_per_language, args.seed)
            max_docs_by_lang[lang] = collect_docs_for_queries(
                lang,
                queries=queries,
                distractors=max_distractors,
                seed=args.seed,
                max_shards=args.max_shards_per_language,
            )

        available_docids = set(max_docs_by_lang[lang])
        filtered_queries = [
            MiraclQuery(
                language=query.language,
                query_id=query.query_id,
                query=query.query,
                positive_docids=tuple(docid for docid in query.positive_docids if docid in available_docids),
            )
            for query in queries
            if any(docid in available_docids for docid in query.positive_docids)
        ]
        if len(filtered_queries) < len(queries):
            print(
                f"[warning] {lang}: using {len(filtered_queries)}/{len(queries)} queries after filtering "
                "to queries with at least one indexed MIRACL positive doc."
            )
        if not filtered_queries:
            raise ValueError(
                f"No {lang} queries have indexed MIRACL positive docs. "
                "Increase --max-shards-per-language or lower language/query scope."
            )

        queries = filtered_queries
        queries_by_lang[lang] = queries
        all_queries.extend(queries)
        required_by_lang[lang] = {docid for query in queries for docid in query.positive_docids}

    scale_results: list[dict[str, Any]] = []

    for distractor_scale in distractor_scales:
        docs_by_lang: dict[str, dict[str, MiraclDoc]] = {}
        for lang in args.languages:
            required = required_by_lang[lang]
            required_docs = {
                docid: doc
                for docid, doc in max_docs_by_lang[lang].items()
                if docid in required
            }
            distractor_docs = [
                doc
                for docid, doc in max_docs_by_lang[lang].items()
                if docid not in required
            ][:distractor_scale]
            docs_by_lang[lang] = {
                **required_docs,
                **{doc.docid: doc for doc in distractor_docs},
            }

        all_docs = [doc for lang_docs in docs_by_lang.values() for doc in lang_docs.values()]

        if args.persistent_profile:
            profile = args.persistent_profile
            data_key = setup_persistent_profile(profile)
            temp_context = None
        else:
            profile = f"miracl-bench-{distractor_scale}-{int(time.time())}"
            temp_context = tempfile.TemporaryDirectory(prefix="matriosha-miracl-bench-")

        if temp_context is None:
            root = None
        else:
            root = Path(temp_context.__enter__())
            data_key = setup_temp_profile(profile, root)

        try:
            embedder = get_default_embedder()
            rows: list[dict[str, Any]] = []

            if args.mode == "local":
                t_index = time.perf_counter()
                store, vector_index, doc_to_memory_id = index_docs(profile, data_key, all_docs)
                index_ms = (time.perf_counter() - t_index) * 1000

                for query in all_queries:
                    returned_ids, candidate_ids, timings = search_once(
                        store,
                        vector_index,
                        embedder,
                        data_key,
                        query.query,
                        args.candidate_limit,
                        args.final_k,
                    )
                    positive_ids = {
                        doc_to_memory_id[f"{query.language}:{docid}"]
                        for docid in query.positive_docids
                        if f"{query.language}:{docid}" in doc_to_memory_id
                    }
                    keyword_hit = bool(positive_ids.intersection(candidate_ids))
                    rank = None
                    for idx, memory_id in enumerate(returned_ids, start=1):
                        if memory_id in positive_ids:
                            rank = idx
                            break

                    rows.append(
                        {
                            "language": query.language,
                            "query_id": query.query_id,
                            "query": query.query,
                            "positive_docids": list(query.positive_docids),
                            "positive_count": len(positive_ids),
                            "keyword_recall_at_50": keyword_hit,
                            "rank": rank,
                            "candidate_count": timings["candidate_count"],
                            "total_ms": round(float(timings["total_ms"]), 2),
                            "terms_ms": round(float(timings["terms_ms"]), 2),
                            "candidate_ms": round(float(timings["candidate_ms"]), 2),
                            "rerank_ms": round(float(timings["rerank_ms"]), 2),
                        }
                    )
            else:
                managed_profile = args.managed_profile
                if managed_profile is None:
                    cfg = load_config()
                    managed_profile = get_active_profile(cfg, None).name
                token = resolve_access_token(managed_profile)
                if not token:
                    raise RuntimeError(
                        f"Managed login required for profile {managed_profile!r}. "
                        f"Run: matriosha --profile {managed_profile} auth login"
                    )

                async def _run_managed_scale() -> tuple[float, dict[str, str], list[dict[str, Any]]]:
                    async with ManagedClient(
                        token=token,
                        base_url=args.managed_endpoint,
                        profile_name=managed_profile,
                    ) as client:
                        t_index_inner = time.perf_counter()
                        doc_to_memory_id_inner = await index_docs_managed(client, data_key, all_docs)
                        index_ms_inner = (time.perf_counter() - t_index_inner) * 1000
                        managed_rows: list[dict[str, Any]] = []

                        for query in all_queries:
                            returned_ids, candidate_ids, timings = await search_once_managed(
                                client,
                                embedder,
                                data_key,
                                query.query,
                                args.candidate_limit,
                                args.final_k,
                            )
                            positive_ids = {
                                doc_to_memory_id_inner[f"{query.language}:{docid}"]
                                for docid in query.positive_docids
                                if f"{query.language}:{docid}" in doc_to_memory_id_inner
                            }
                            keyword_hit = bool(positive_ids.intersection(candidate_ids))
                            rank = None
                            for idx, memory_id in enumerate(returned_ids, start=1):
                                if memory_id in positive_ids:
                                    rank = idx
                                    break

                            managed_rows.append(
                                {
                                    "language": query.language,
                                    "query_id": query.query_id,
                                    "query": query.query,
                                    "positive_docids": list(query.positive_docids),
                                    "positive_count": len(positive_ids),
                                    "keyword_recall_at_50": keyword_hit,
                                    "rank": rank,
                                    "candidate_count": timings["candidate_count"],
                                    "total_ms": round(float(timings["total_ms"]), 2),
                                    "terms_ms": round(float(timings["terms_ms"]), 2),
                                    "candidate_ms": round(float(timings["candidate_ms"]), 2),
                                    "rerank_ms": round(float(timings["rerank_ms"]), 2),
                                }
                            )
                        return index_ms_inner, doc_to_memory_id_inner, managed_rows

                index_ms, _doc_to_memory_id, rows = asyncio.run(_run_managed_scale())
        finally:
            if temp_context is not None:
                temp_context.__exit__(None, None, None)

        overall = summarize_rows(rows, args.candidate_limit, args.final_k)

        by_language = {}
        for lang in args.languages:
            lang_rows = [row for row in rows if row["language"] == lang]
            if lang_rows:
                by_language[lang] = summarize_rows(lang_rows, args.candidate_limit, args.final_k)

        scale_result: dict[str, Any] = {
            "distractors_per_language": distractor_scale,
            "indexed_docs": len(all_docs),
            "index_ms": round(index_ms, 2),
            "summary": overall,
            "by_language": by_language,
        }
        if args.rows:
            scale_result["rows"] = rows
        scale_results.append(scale_result)

    result = {
        "timestamp": started,
        "benchmark": "miracl_derived_matriosha_retrieval",
        "source": {
            "topics": "miracl/miracl",
            "qrels": "miracl/miracl",
            "corpus": "miracl/miracl-corpus",
            "split": args.split,
        },
        "embedder": os.environ.get("MATRIOSHA_EMBEDDER"),
        "languages": args.languages,
        "queries_per_language": args.queries_per_language,
        "query_source": args.query_source,
        "distractor_scales": distractor_scales,
        "scales": scale_results,
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = started.replace(":", "").replace(".", "")
    out = output_dir / f"miracl_retrieval_{stamp}.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Matriosha MIRACL-backed retrieval benchmark | embedder={result['embedder']}")
    print(f"Languages: {', '.join(args.languages)}")
    print()
    print("| Distractors/lang | Indexed docs | Queries | Keyword Recall@50 | Hit@1 | Hit@5 | MRR | p50 total | p95 total | cand p50 |")
    print("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for scale_result in scale_results:
        s = scale_result["summary"]
        print(
            f"| {scale_result['distractors_per_language']} | {scale_result['indexed_docs']} | {s['queries']} | "
            f"{s['keyword_recall_at_50']:.2%} | {s['hit_at_1']:.2%} | {s['hit_at_5']:.2%} | "
            f"{s['mrr']:.3f} | {s['latency_total_p50_ms']:.2f} ms | "
            f"{s['latency_total_p95_ms']:.2f} ms | {s['candidate_count_p50']} |"
        )

    print()
    print("Saved:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
