#!/usr/bin/env python3
"""Persistent MIRACL corpus indexer for Matriosha retrieval benchmarks.

This indexes MIRACL corpus passages once into local and/or managed Matriosha
storage, then writes a manifest that later evaluation scripts can reuse.

It intentionally does NOT evaluate retrieval. It only builds the benchmark index.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from huggingface_hub import hf_hub_download, list_repo_files

from matriosha.core.binary_protocol import encode_envelope, envelope_to_json
from matriosha.core.config import (
    MatrioshaConfig,
    Profile,
    get_active_profile,
    load_config,
    save_config,
)
from matriosha.core.managed.auth import resolve_access_token
from matriosha.core.managed.client import ManagedClient
from matriosha.core.search_terms import (
    build_retrieval_index_text,
    extract_search_terms,
    keyed_search_tokens,
)
from matriosha.core.storage_local import LocalStore
from matriosha.core.vault import Vault
from matriosha.core.vectors import LocalVectorIndex, get_default_embedder


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def memory_id_for_doc(language: str, docid: str) -> str:
    return f"miracl-{uuid5(NAMESPACE_URL, f'miracl:{language}:{docid}')}"


def shard_num(path: str) -> int:
    name = Path(path).name
    digits = "".join(ch for ch in name if ch.isdigit())
    return int(digits or 0)


def setup_persistent_profile(profile: str, passphrase: str) -> bytes:
    try:
        vault = Vault.unlock(profile, passphrase)
    except Exception:
        cfg = load_config()
        profiles = dict(cfg.profiles)
        profiles[profile] = Profile(name=profile, mode="local", sync_dir=None)
        save_config(MatrioshaConfig(active_profile=profile, profiles=profiles))
        vault = Vault.init(profile, passphrase, force=False)
    return vault.data_key


def corpus_shards(language: str) -> list[str]:
    files = sorted(list_repo_files("miracl/miracl-corpus", repo_type="dataset"))
    shards = [
        f
        for f in files
        if f.startswith(f"miracl-corpus-v1.0-{language}/") and f.endswith(".jsonl.gz")
    ]
    return sorted(shards, key=shard_num)


def parse_doc(line: str) -> tuple[str, str, str]:
    row = json.loads(line)
    docid = str(row.get("docid") or row.get("_id") or row.get("id") or "")
    title = str(row.get("title") or "")
    text = str(row.get("text") or row.get("contents") or "")
    return docid, title, text


def token_hashes_for_text(
    *,
    text: str,
    tags: list[str],
    data_key: bytes,
) -> list[str]:
    index_text = build_retrieval_index_text(text)
    terms = extract_search_terms(index_text, tuple(tags), "text/plain", "text")
    return keyed_search_tokens(terms, data_key)


def build_envelope(
    *,
    language: str,
    docid: str,
    title: str,
    text: str,
    data_key: bytes,
    mode: str,
) -> tuple[Any, bytes, list[str], list[float]]:
    memory_id = memory_id_for_doc(language, docid)
    memory_text = f"{title}\n\n{text}".strip()
    tags = [f"miracl:{language}", "miracl", "benchmark"]

    env, b64_payload = encode_envelope(
        memory_text.encode("utf-8"),
        data_key,
        mode=mode,
        tags=tags,
        source="cli",
        mime_type="text/plain",
        content_kind="text",
    )
    env.memory_id = memory_id

    tokens = token_hashes_for_text(text=memory_text, tags=tags, data_key=data_key)
    embedder = get_default_embedder()
    embedding = [float(value) for value in embedder.embed(memory_text[:4096])]
    return env, b64_payload, tokens, embedding


def index_local_doc(
    *,
    store: LocalStore,
    vector_index: LocalVectorIndex,
    language: str,
    docid: str,
    title: str,
    text: str,
    data_key: bytes,
) -> bool:
    memory_id = memory_id_for_doc(language, docid)
    if store.get(memory_id) is not None:
        return False

    env, b64_payload, tokens, embedding = build_envelope(
        language=language,
        docid=docid,
        title=title,
        text=text,
        data_key=data_key,
        mode="local",
    )
    import numpy as np

    store.put(
        env,
        b64_payload,
        np.asarray(embedding, dtype=np.float32),
        keyword_tokens=tokens,
    )
    return True


async def index_managed_doc(
    *,
    client: ManagedClient,
    language: str,
    docid: str,
    title: str,
    text: str,
    data_key: bytes,
) -> bool:
    env, b64_payload, tokens, embedding = build_envelope(
        language=language,
        docid=docid,
        title=title,
        text=text,
        data_key=data_key,
        mode="managed",
    )
    await client.upload_memory(
        json.loads(envelope_to_json(env)),
        b64_payload,
        embedding,
        metadata_hashes=tokens,
    )
    return True


async def main_async() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("local", "managed", "both"), default="both")
    parser.add_argument("--languages", nargs="+", default=["en"])
    parser.add_argument("--profile", default="miracl-bench")
    parser.add_argument("--passphrase", default="benchmark-passphrase")
    parser.add_argument("--managed-profile", default=None)
    parser.add_argument("--managed-endpoint", default=None)
    parser.add_argument("--max-docs-per-language", type=int, default=None)
    parser.add_argument("--max-shards-per-language", type=int, default=None)
    parser.add_argument("--progress-every", type=int, default=1000)
    parser.add_argument("--output-dir", default="benchmarks/results")
    args = parser.parse_args()

    os.environ.setdefault("MATRIOSHA_EMBEDDER", "hash")

    data_key = setup_persistent_profile(args.profile, args.passphrase)

    store = LocalStore(args.profile) if args.mode in ("local", "both") else None
    vector_index = LocalVectorIndex(args.profile) if args.mode in ("local", "both") else None

    managed_client: ManagedClient | None = None
    if args.mode in ("managed", "both"):
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

        managed_client = ManagedClient(
            token=token,
            base_url=args.managed_endpoint,
            profile_name=managed_profile,
        )
        await managed_client.__aenter__()

    started = utc_now()
    t0 = time.perf_counter()

    manifest: dict[str, Any] = {
        "benchmark": "miracl_persistent_index",
        "started_at": started,
        "mode": args.mode,
        "profile": args.profile,
        "managed_profile": args.managed_profile,
        "embedder": os.environ.get("MATRIOSHA_EMBEDDER"),
        "languages": {},
        "docs": {},
    }

    try:
        for language in args.languages:
            shards = corpus_shards(language)
            if args.max_shards_per_language is not None:
                shards = shards[: args.max_shards_per_language]

            local_indexed = 0
            managed_indexed = 0
            seen = 0
            skipped_existing_local = 0
            lang_start = time.perf_counter()

            print(f"[{utc_now()}] language={language} shards={len(shards)}")

            for shard_idx, shard in enumerate(shards, start=1):
                local_path = hf_hub_download(
                    repo_id="miracl/miracl-corpus",
                    repo_type="dataset",
                    filename=shard,
                )

                print(
                    f"[{utc_now()}] language={language} shard={shard_idx}/{len(shards)} file={Path(shard).name}"
                )

                with gzip.open(local_path, "rt", encoding="utf-8") as handle:
                    for line in handle:
                        docid, title, body = parse_doc(line)
                        if not docid:
                            continue

                        seen += 1
                        memory_id = memory_id_for_doc(language, docid)

                        if store is not None and vector_index is not None:
                            did_index = index_local_doc(
                                store=store,
                                vector_index=vector_index,
                                language=language,
                                docid=docid,
                                title=title,
                                text=body,
                                data_key=data_key,
                            )
                            if did_index:
                                local_indexed += 1
                            else:
                                skipped_existing_local += 1

                        if managed_client is not None:
                            await index_managed_doc(
                                client=managed_client,
                                language=language,
                                docid=docid,
                                title=title,
                                text=body,
                                data_key=data_key,
                            )
                            managed_indexed += 1

                        manifest["docs"][f"{language}:{docid}"] = memory_id

                        if args.progress_every and seen % args.progress_every == 0:
                            elapsed = time.perf_counter() - lang_start
                            rate = seen / elapsed if elapsed > 0 else 0.0
                            print(
                                f"[{utc_now()}] language={language} seen={seen} "
                                f"local_indexed={local_indexed} managed_indexed={managed_indexed} "
                                f"skipped_local={skipped_existing_local} rate={rate:.1f}/s"
                            )

                        if (
                            args.max_docs_per_language is not None
                            and seen >= args.max_docs_per_language
                        ):
                            break

                if args.max_docs_per_language is not None and seen >= args.max_docs_per_language:
                    break

            manifest["languages"][language] = {
                "seen": seen,
                "local_indexed": local_indexed,
                "managed_indexed": managed_indexed,
                "skipped_existing_local": skipped_existing_local,
                "shards_scanned": min(len(shards), shard_idx if shards else 0),
                "elapsed_sec": round(time.perf_counter() - lang_start, 2),
            }

    finally:
        if managed_client is not None:
            await managed_client.__aexit__(None, None, None)

    manifest["finished_at"] = utc_now()
    manifest["elapsed_sec"] = round(time.perf_counter() - t0, 2)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out = (
        output_dir
        / f"miracl_index_manifest_{args.mode}_{started.replace(':', '').replace('.', '')}.json"
    )
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    latest = output_dir / f"miracl_index_manifest_{args.mode}_latest.json"
    latest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print("Index complete.")
    print("Manifest:", out)
    print("Latest:", latest)
    print(
        json.dumps({k: v for k, v in manifest.items() if k != "docs"}, indent=2, ensure_ascii=False)
    )
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
