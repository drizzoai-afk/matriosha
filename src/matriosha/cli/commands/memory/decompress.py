"""`matriosha memory decompress` command."""

from __future__ import annotations

import typer
from typing import cast

from .common import (
    AuthError,
    EXIT_AUTH,
    EXIT_INTEGRITY,
    EXIT_UNKNOWN,
    EXIT_USAGE,
    IntegrityError,
    InvalidInput,
    LocalStore,
    LocalVectorIndex,
    Vault,
    VaultIntegrityError,
    _cosine_similarity,
    _emit_error,
    _render_panel,
    _require_managed_session_for_memory,
    _resolve_passphrase,
    _short,
    decode_envelope,
    get_active_profile,
    get_default_embedder,
    json,
    load_config,
    make_console,
    np,
    resolve_output,
)


def register(app: typer.Typer) -> None:
    @app.command("decompress")
    def decompress(
        ctx: typer.Context,
        parent_id: str = typer.Argument(..., help="Compressed parent memory id to expand."),
        keep_parent: bool = typer.Option(False, "--keep-parent", help="Keep parent memory after successful restore."),
        min_similarity: float = typer.Option(0.9, "--min-similarity", help="Minimum child-parent cosine similarity."),
        json_output_flag: bool = typer.Option(False, "--json", help="Show JSON output for scripts and automation."),
    ) -> None:
        """Restore memories from a compressed memory group."""

        output = resolve_output(ctx, json_flag=json_output_flag)
        gctx = output.ctx
        json_output = gctx.json_output
        console = make_console()

        try:
            if min_similarity < -1.0 or min_similarity > 1.0:
                raise InvalidInput("--min-similarity must be between -1.0 and 1.0")

            cfg = load_config()
            profile = get_active_profile(cfg, gctx.profile)
            _require_managed_session_for_memory(profile, json_output=json_output, plain=gctx.plain, console=console)
            store = LocalStore(profile.name)
            index = LocalVectorIndex(profile.name)
            embedder = get_default_embedder()
            vault = Vault.unlock(profile.name, _resolve_passphrase(profile_name=profile.name, profile_mode=profile.mode, json_output=json_output))

            try:
                parent_env, parent_payload = store.get(parent_id)
            except FileNotFoundError as exc:
                raise InvalidInput(f"parent memory not found: {parent_id}") from exc

            if not parent_env.children:
                if json_output:
                    typer.echo(json.dumps({"status": "error", "message": "not a compressed parent", "exit": EXIT_USAGE}))
                else:
                    typer.echo("not a compressed parent")
                raise typer.Exit(code=EXIT_USAGE)

            parent_vec = index.get_vector(parent_id)
            if parent_vec is None:
                parent_plaintext = decode_envelope(parent_env, parent_payload, vault.data_key)
                parent_input = parent_plaintext[: 4 * 1024].decode("utf-8", errors="replace")
                parent_vec = embedder.embed(parent_input)
                index.add(parent_id, parent_vec, entry_type="parent", is_active=True)
                index.save()

            restored_vectors: list[tuple[str, np.ndarray]] = []
            failing_children: list[dict[str, object]] = []

            for child_id in parent_env.children:
                try:
                    child_env, child_payload = store.get(child_id)
                    child_plaintext = decode_envelope(child_env, child_payload, vault.data_key)
                except FileNotFoundError:
                    failing_children.append({"memory_id": child_id, "reason": "missing"})
                    continue

                child_input = child_plaintext[: 4 * 1024].decode("utf-8", errors="replace")
                child_vec = embedder.embed(child_input)
                similarity = _cosine_similarity(child_vec, parent_vec)

                if similarity < min_similarity:
                    failing_children.append({"memory_id": child_id, "similarity": similarity})
                    continue

                restored_vectors.append((child_id, child_vec))

            if failing_children:
                if json_output:
                    typer.echo(
                        json.dumps(
                            {
                                "status": "error",
                                "message": "integrity check failed",
                                "exit": EXIT_INTEGRITY,
                                "failing_children": failing_children,
                            }
                        )
                    )
                else:
                    typer.echo("integrity check failed")
                    for item in failing_children:
                        if "similarity" in item:
                            typer.echo(f"- {item['memory_id']} similarity={float(cast(float | int | str, item['similarity'])):.6f}")
                        else:
                            typer.echo(f"- {item['memory_id']} reason={item['reason']}")
                raise typer.Exit(code=EXIT_INTEGRITY)

            for child_id, child_vec in restored_vectors:
                index.add(child_id, child_vec, entry_type="memory", is_active=True)
            index.save()

            parent_deleted = False
            if not keep_parent:
                parent_deleted = store.delete(parent_id)

            restored_ids = [memory_id for memory_id, _ in restored_vectors]
            payload = {"restored": restored_ids, "parent_deleted": parent_deleted}

            if json_output:
                typer.echo(json.dumps(payload))
                raise typer.Exit(code=0)

            if gctx.plain:
                typer.echo(f"restored: {','.join(restored_ids)}")
                typer.echo(f"parent_deleted: {str(parent_deleted).lower()}")
                raise typer.Exit(code=0)

            _render_panel(
                "MEMORY DECOMPRESS",
                [
                    ("parent", _short(parent_id, head=12, tail=6)),
                    ("restored", str(len(restored_ids))),
                    ("parent_deleted", str(parent_deleted).lower()),
                ],
                status_chip="✓ SUCCESS",
                style="success",
                console=console,
            )
            raise typer.Exit(code=0)

        except InvalidInput as exc:
            _emit_error(
                title="Invalid decompress input",
                category="VAL",
                stable_code="VAL-007",
                exit_code=EXIT_USAGE,
                fix="provide a valid parent id and --min-similarity in range [-1.0, 1.0]",
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
                debug=f"memory_id={parent_id} phase=memory.decompress",
                json_output=json_output,
                plain=gctx.plain,
                console=console,
            )
            raise typer.Exit(code=EXIT_INTEGRITY)
        except (VaultIntegrityError, OSError, ValueError) as exc:
            _emit_error(
                title="Local storage operation failed",
                category="STORE",
                stable_code="STORE-007",
                exit_code=EXIT_UNKNOWN,
                fix="check local memory files and vector index, then retry",
                debug=f"os_error={type(exc).__name__}",
                json_output=json_output,
                plain=gctx.plain,
                console=console,
            )
            raise typer.Exit(code=EXIT_UNKNOWN)
