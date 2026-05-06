#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import re
from pathlib import Path

from huggingface_hub import hf_hub_download, list_repo_files


def shard_num(path: str) -> int:
    name = Path(path).name
    digits = "".join(ch for ch in name if ch.isdigit())
    return int(digits or 0)


def safe_key(language: str, docid: str) -> str:
    safe_docid = re.sub(r"[^A-Za-z0-9_:.\\-]", "_", docid)
    return f"miracl::{language}::{safe_docid}"[:128]


def corpus_shards(language: str) -> list[str]:
    files = sorted(list_repo_files("miracl/miracl-corpus", repo_type="dataset"))
    shards = [
        f
        for f in files
        if f.startswith(f"miracl-corpus-v1.0-{language}/") and f.endswith(".jsonl.gz")
    ]
    return sorted(shards, key=shard_num)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--languages", nargs="+", required=True)
    parser.add_argument("--docs-per-language", type=int, default=1000)
    parser.add_argument("--queries-per-language", type=int, default=100)
    parser.add_argument("--max-shards-per-language", type=int, default=None)
    parser.add_argument("--output-dir", default="benchmarks/fixtures")
    parser.add_argument("--prefix", default="miracl_self")
    parser.add_argument(
        "--query-style",
        choices=("exact", "title", "middle"),
        default="exact",
        help="exact uses first 32 words of the memory body; title uses document title when available; middle uses a short middle snippet.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    memory_path = output_dir / f"{args.prefix}_memories.jsonl"
    query_path = output_dir / f"{args.prefix}_queries.jsonl"
    manifest_path = output_dir / f"{args.prefix}_manifest.json"

    manifest = {
        "fixture": "miracl_self_retrieval",
        "note": "MIRACL corpus self-retrieval fixture, not official MIRACL qrels evaluation.",
        "query_style": args.query_style,
        "languages": {},
        "memory_fixture": str(memory_path),
        "query_fixture": str(query_path),
    }

    total_memories = 0
    total_queries = 0

    with (
        memory_path.open("w", encoding="utf-8") as mem_out,
        query_path.open("w", encoding="utf-8") as query_out,
    ):
        for language in args.languages:
            shards = corpus_shards(language)
            if args.max_shards_per_language is not None:
                shards = shards[: args.max_shards_per_language]

            lang_docs = 0
            lang_queries = 0
            shards_scanned = 0

            print(f"language={language} shards={len(shards)}")

            for shard in shards:
                if lang_docs >= args.docs_per_language:
                    break

                local = hf_hub_download(
                    repo_id="miracl/miracl-corpus",
                    repo_type="dataset",
                    filename=shard,
                )
                shards_scanned += 1

                with gzip.open(local, "rt", encoding="utf-8") as handle:
                    for line in handle:
                        if lang_docs >= args.docs_per_language:
                            break
                        if not line.strip():
                            continue

                        row = json.loads(line)
                        docid = str(row.get("docid") or row.get("_id") or row.get("id") or "")
                        if not docid:
                            continue

                        title = str(row.get("title") or "").strip()
                        text = str(row.get("text") or row.get("contents") or "").strip()
                        body = f"{title}\n\n{text}".strip()
                        if not body:
                            continue

                        key = safe_key(language, docid)
                        tags = [f"miracl:{language}", "miracl", "benchmark", "self-retrieval"]

                        mem_out.write(
                            json.dumps(
                                {
                                    "key": key,
                                    "text": body,
                                    "tags": tags,
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )

                        if lang_queries < args.queries_per_language:
                            words = body.split()
                            if args.query_style == "title" and title:
                                query_text = title
                            elif args.query_style == "middle" and len(words) > 48:
                                start = max(8, len(words) // 2 - 12)
                                query_text = " ".join(words[start : start + 24])
                            else:
                                query_text = " ".join(words[:32])
                            query_out.write(
                                json.dumps(
                                    {
                                        "query": query_text,
                                        "expected_key": key,
                                        "category": f"miracl_self:{language}",
                                    },
                                    ensure_ascii=False,
                                )
                                + "\n"
                            )
                            lang_queries += 1
                            total_queries += 1

                        lang_docs += 1
                        total_memories += 1

            manifest["languages"][language] = {
                "docs": lang_docs,
                "queries": lang_queries,
                "shards_scanned": shards_scanned,
            }

    manifest["total_memories"] = total_memories
    manifest["total_queries"] = total_queries
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print("Wrote:", memory_path)
    print("Wrote:", query_path)
    print("Wrote:", manifest_path)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
