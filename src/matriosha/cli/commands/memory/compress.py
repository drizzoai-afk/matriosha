"""`matriosha memory compress` command."""

from __future__ import annotations

import json
from typing import cast

import jax.numpy as jnp
import typer
from rich.tree import Tree

from matriosha.core.crypto import IntegrityError
from matriosha.core.vault import AuthError, Vault, VaultIntegrityError
from matriosha.cli.commands.memory.common import InvalidInput
from matriosha.cli.brand.theme import console as make_console
from matriosha.cli.utils.output import resolve_output
from matriosha.core.config import get_active_profile, load_config
from matriosha.core.binary_protocol import decode_envelope, encode_envelope
from matriosha.core.storage_local import LocalStore
from matriosha.core.vectors import LocalVectorIndex

from .common import (
    EXIT_AUTH,
    EXIT_INTEGRITY,
    EXIT_UNKNOWN,
    EXIT_USAGE,
    _cosine_similarity,
    _emit_error,
    _require_managed_session_for_memory,
    _resolve_passphrase,
)


def compress(
    ctx: typer.Context,
    threshold: float = typer.Option(0.9, "--threshold", help="Cluster threshold for cosine similarity."),
    deduplicate: bool = typer.Option(True, "--deduplicate/--no-deduplicate", help="Enable deduplication clustering mode."),
    tag: str | None = typer.Option(None, "--tag", help="Only consider memories containing this tag."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview clusters without writing parent memories."),
    json_output_flag: bool = typer.Option(False, "--json", help="Show JSON output for scripts and automation."),
) -> None:
    """Reduce storage use by grouping similar memories."""

    output = resolve_output(ctx, json_flag=json_output_flag)
    gctx = output.ctx
    json_output = gctx.json_output
    console = make_console()

    try:
        if threshold < -1.0 or threshold > 1.0:
            raise InvalidInput("--threshold must be between -1.0 and 1.0")

        cfg = load_config()
        profile = get_active_profile(cfg, gctx.profile)
        _require_managed_session_for_memory(profile, json_output=json_output, plain=gctx.plain, console=console)
        store = LocalStore(profile.name)
        index = LocalVectorIndex(profile.name)
        vault = Vault.unlock(profile.name, _resolve_passphrase(profile_name=profile.name, profile_mode=profile.mode, json_output=json_output))

        all_envs = store.list(tag=tag, limit=1_000_000)
        env_by_id = {env.memory_id: env for env in all_envs}
        vector_by_id: dict[str, jnp.ndarray] = {}

        for idx, memory_id in enumerate(index._ids):  # noqa: SLF001 - internal store for local clustering
            if memory_id not in env_by_id:
                continue
            vector_by_id[memory_id] = jnp.asarray(index._vectors[idx], dtype=jnp.float32)  # noqa: SLF001

        candidate_ids = [env.memory_id for env in all_envs if env.memory_id in vector_by_id]
        remaining = list(candidate_ids)

        clusters: list[list[str]] = []
        while remaining:
            seed = remaining[0]
            seed_vec = vector_by_id[seed]

            cluster = [seed]
            for candidate in remaining[1:]:
                sim = _cosine_similarity(seed_vec, vector_by_id[candidate])
                if sim >= threshold:
                    cluster.append(candidate)

            clusters.append(cluster)
            clustered = set(cluster)
            remaining = [memory_id for memory_id in remaining if memory_id not in clustered]

        parent_records: list[dict[str, object]] = []

        for cluster in clusters:
            if len(cluster) < 2:
                continue

            plaintext_parts: list[bytes] = []
            cluster_tags: set[str] = set()

            for memory_id in cluster:
                env, b64_payload = store.get(memory_id)
                plaintext_parts.append(decode_envelope(env, b64_payload, vault.data_key))
                cluster_tags.update(env.tags)

            merged_plaintext = b"\n---\n".join(plaintext_parts)
            merged_tags = sorted(cluster_tags.union({"compressed", "parent"}))

            parent_env, parent_payload = encode_envelope(
                merged_plaintext,
                vault.data_key,
                mode=profile.mode,
                tags=merged_tags,
                source="cli",
            )
            parent_env.children = list(cluster)

            if not dry_run:
                cluster_vectors = [vector_by_id[memory_id] for memory_id in cluster]
                centroid = jnp.mean(jnp.vstack(cluster_vectors), axis=0).astype(jnp.float32)
                norm = float(jnp.linalg.norm(centroid))
                if norm > 0.0:
                    centroid = (centroid / norm).astype(jnp.float32)
                store.put(parent_env, parent_payload, embedding=centroid, embedding_kind="parent", is_active=True)

            parent_records.append(
                {
                    "parent_id": parent_env.memory_id,
                    "children": list(cluster),
                    "size": len(cluster),
                    "tags": merged_tags,
                }
            )

        result = {
            "dry_run": dry_run,
            "threshold": threshold,
            "deduplicate": deduplicate,
            "tag": tag,
            "candidate_count": len(candidate_ids),
            "cluster_count": len(parent_records),
            "created_parents": parent_records,
            "singleton_count": sum(1 for cluster in clusters if len(cluster) == 1),
        }

        if json_output:
            typer.echo(json.dumps(result))
            raise typer.Exit(code=0)

        if gctx.plain:
            typer.echo(
                f"clusters={result['cluster_count']} singletons={result['singleton_count']} dry_run={str(dry_run).lower()}"
            )
            for cluster_idx, parent in enumerate(parent_records, start=1):
                typer.echo(
                    f"cluster_{cluster_idx}\tparent={parent['parent_id']}\tsize={parent['size']}\t"
                    f"children={','.join(cast(list[str], parent['children']))}"
                )
            if not parent_records:
                typer.echo("no clusters found")
            raise typer.Exit(code=0)

        title = "Memory Compress (dry-run)" if dry_run else "Memory Compress"
        root = Tree(f"[bold cyan]{title}[/bold cyan]")
        root.add(f"threshold={threshold:.2f} candidates={len(candidate_ids)}")

        if parent_records:
            for cluster_idx, parent in enumerate(parent_records, start=1):
                cluster_node = root.add(
                    f"cluster {cluster_idx}: parent={parent['parent_id']} size={parent['size']}"
                )
                children_node = cluster_node.add("children")
                for child_id in cast(list[str], parent["children"]):
                    children_node.add(child_id)
        else:
            root.add("no merge clusters found")

        root.add(f"singletons untouched: {result['singleton_count']}")
        console.print(root)
        raise typer.Exit(code=0)

    except InvalidInput as exc:
        _emit_error(
            title="Invalid compress input",
            category="VAL",
            stable_code="VAL-006",
            exit_code=EXIT_USAGE,
            fix="provide --threshold in range [-1.0, 1.0] and valid tag filters",
            debug=f"detail={exc}",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_USAGE)
    except AuthError:
        _emit_error(
            title="Vault unlock failed",
            category="AUTH",
            stable_code="AUTH-002",
            exit_code=EXIT_AUTH,
            fix="Use the correct vault passphrase and try again.",
            debug="provider=local_vault profile_auth_failed",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_AUTH)
    except IntegrityError:
        _emit_error(
            title="Memory integrity verification failed",
            category="SYS",
            stable_code="SYS-011",
            exit_code=EXIT_INTEGRITY,
            fix="run `matriosha vault verify --deep` to inspect corrupted entries",
            debug="phase=memory.compress preview_decode_failed",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_INTEGRITY)
    except (VaultIntegrityError, OSError, ValueError) as exc:
        _emit_error(
            title="Local storage operation failed",
            category="STORE",
            stable_code="STORE-006",
            exit_code=EXIT_UNKNOWN,
            fix="check local memory files and vector index, then retry",
            debug=f"os_error={type(exc).__name__}",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_UNKNOWN)


def register(app: typer.Typer) -> None:
    app.command("compress")(compress)
