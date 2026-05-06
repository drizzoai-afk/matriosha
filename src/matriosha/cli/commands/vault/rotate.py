"""Vault rotate command."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import typer

from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_AUTH, EXIT_OK, EXIT_USAGE
from matriosha.core.binary_protocol import decode_envelope
from matriosha.core.config import get_active_profile, load_config
from matriosha.core.crypto import derive_key, encrypt, generate_salt
from matriosha.core.managed.auth import ensure_process_managed_passphrase, resolve_access_token
from matriosha.core.managed.client import ManagedClient
from matriosha.core.managed.key_custody import double_wrap, upload_wrapped_key
from matriosha.core.managed.sync import SyncEngine
from matriosha.core.secrets import get_secret
from matriosha.core.storage_local import LocalStore
from matriosha.core.vault import AuthError, DATA_KEY_LEN, MAGIC, Vault
from matriosha.core.vectors import get_default_embedder

from .common import _render_card


def _vault_package_patchable(name: str, fallback):
    import sys

    package = sys.modules.get("matriosha.cli.commands.vault")
    return getattr(package, name, fallback) if package is not None else fallback


def register(app: typer.Typer) -> None:
    def _resolve_unlock_passphrase(*, override: str | None = None) -> str:
        if override is not None:
            return override
        env_passphrase = os.getenv("MATRIOSHA_PASSPHRASE")
        if env_passphrase:
            return env_passphrase
        return typer.prompt("Current vault passphrase", hide_input=True)

    def _resolve_new_passphrase(*, override: str | None = None) -> str:
        if override is not None:
            return override
        env_passphrase = os.getenv("MATRIOSHA_NEW_PASSPHRASE")
        if env_passphrase:
            return env_passphrase
        return typer.prompt("New vault passphrase", hide_input=True, confirmation_prompt=True)

    def _build_wrapped_key_material(data_key: bytes, passphrase: str) -> tuple[bytes, bytes, bytes]:
        salt = generate_salt(16)
        kek = derive_key(passphrase, salt)
        nonce, ciphertext = encrypt(data_key, kek)
        wrapped_blob = MAGIC + nonce + ciphertext
        return salt, kek, wrapped_blob

    def _safe_write_json(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, separators=(",", ":"), sort_keys=True), encoding="utf-8"
        )
        if os.name != "nt":
            os.chmod(path, 0o600)

    def _rotation_marker_path(root: Path) -> Path:
        return root / "rotate.marker.json"

    def _collect_memory_ids(memories_dir: Path) -> list[str]:
        ids: list[str] = []
        for env_file in sorted(memories_dir.glob("*.env.json")):
            memory_id = env_file.name.removesuffix(".env.json")
            payload_file = memories_dir / f"{memory_id}.bin.b64"
            if payload_file.exists():
                ids.append(memory_id)
        return ids

    def _reencrypt_memories_with_marker(
        *,
        profile_name: str,
        old_key: bytes,
        new_key: bytes,
        crash_after: int | None,
    ) -> tuple[int, bool]:
        store = LocalStore(profile_name)
        root = store.root
        memories_dir = root / "memories"
        tmp_dir = root / "memories.rotate.tmp"
        marker_path = _rotation_marker_path(root)

        resumed = marker_path.exists()
        if resumed:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        else:
            memory_ids = _collect_memory_ids(memories_dir)
            marker = {
                "version": 1,
                "status": "in_progress",
                "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "memory_ids": memory_ids,
                "completed": [],
                "active_dir": str(memories_dir),
                "tmp_dir": str(tmp_dir),
            }
            _safe_write_json(marker_path, marker)

        tmp_dir.mkdir(parents=True, exist_ok=True)

        memory_ids = [str(mid) for mid in marker.get("memory_ids", [])]
        completed = {str(mid) for mid in marker.get("completed", [])}
        processed_this_run = 0

        for memory_id in memory_ids:
            if memory_id in completed:
                continue

            env, b64_payload = store.get(memory_id)
            plaintext = decode_envelope(env, b64_payload, old_key)
            nonce, ciphertext = encrypt(plaintext, new_key)
            reencrypted_b64 = base64.b64encode(nonce + ciphertext)

            env_src = memories_dir / f"{memory_id}.env.json"
            env_dst = tmp_dir / env_src.name
            payload_dst = tmp_dir / f"{memory_id}.bin.b64"

            shutil.copy2(env_src, env_dst)
            payload_dst.write_bytes(reencrypted_b64)
            if os.name != "nt":
                os.chmod(payload_dst, 0o600)

            completed.add(memory_id)
            marker["completed"] = sorted(completed)
            marker["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            _safe_write_json(marker_path, marker)

            processed_this_run += 1
            if crash_after is not None and processed_this_run >= crash_after:
                raise RuntimeError("simulated rotate crash")

        backup_dir = root / "memories.rotate.backup"
        if backup_dir.exists():
            shutil.rmtree(backup_dir)

        os.replace(memories_dir, backup_dir)
        os.replace(tmp_dir, memories_dir)
        shutil.rmtree(backup_dir)

        marker_payload = json.loads(marker_path.read_text(encoding="utf-8"))
        marker_payload["status"] = "completed"
        marker_payload["completed_at"] = (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )
        _safe_write_json(marker_path, marker_payload)
        marker_path.unlink(missing_ok=True)

        return len(memory_ids), resumed

    @app.command("rotate")
    def rotate(
        ctx: typer.Context,
        new_passphrase: str | None = typer.Option(
            None, "--new-passphrase", help="New vault passphrase."
        ),
        current_passphrase: str | None = typer.Option(
            None, "--current-passphrase", help="Current vault passphrase."
        ),
        rotate_data_key: bool = typer.Option(
            False,
            "--rotate-data-key",
            help="Generate a new data key and re-encrypt every local memory payload.",
        ),
        confirm_bulk: bool = typer.Option(
            False,
            "--confirm-bulk",
            help="Required acknowledgement for --rotate-data-key destructive bulk re-encryption.",
        ),
        json_output_flag: bool = typer.Option(
            False, "--json", help="Show JSON output for scripts and automation."
        ),
    ) -> None:
        """Change encryption wrapping safely."""

        gctx = get_global_context(ctx)
        json_output = gctx.json_output or json_output_flag

        cfg = load_config()
        profile = get_active_profile(cfg, gctx.profile)

        if profile.mode == "managed":
            old_passphrase = ensure_process_managed_passphrase(profile.name)
            if not old_passphrase:
                message = "managed key session missing; run `matriosha auth login`"
                if json_output:
                    typer.echo(json.dumps({"status": "error", "error": message}))
                else:
                    typer.echo(message)
                raise typer.Exit(code=EXIT_AUTH)
            # Managed mode avoids prompting; explicit --new-passphrase is still honored for rotation flows.
            new_passphrase_resolved = new_passphrase or old_passphrase
        else:
            old_passphrase = _resolve_unlock_passphrase(override=current_passphrase)
            new_passphrase_resolved = _resolve_new_passphrase(override=new_passphrase)

            if old_passphrase == new_passphrase_resolved and not rotate_data_key:
                message = "new passphrase must differ from current passphrase"
                if json_output:
                    typer.echo(json.dumps({"status": "error", "error": message}))
                else:
                    typer.echo(message)
                raise typer.Exit(code=EXIT_USAGE)

        if rotate_data_key and not confirm_bulk:
            message = "--rotate-data-key requires --confirm-bulk"
            if json_output:
                typer.echo(json.dumps({"status": "error", "error": message}))
            else:
                typer.echo(message)
            raise typer.Exit(code=EXIT_USAGE)

        try:
            vault = Vault.unlock(profile.name, old_passphrase)
        except AuthError:
            if json_output:
                typer.echo(json.dumps({"status": "error", "error": "vault unlock failed"}))
            else:
                typer.echo("vault unlock failed")
            raise typer.Exit(code=EXIT_AUTH)

        resulting_data_key = vault.data_key
        reencrypted_memories = 0
        resumed = False

        try:
            if rotate_data_key:
                resulting_data_key = os.urandom(DATA_KEY_LEN)
                crash_after_raw = os.getenv("MATRIOSHA_ROTATE_CRASH_AFTER")
                crash_after = int(crash_after_raw) if crash_after_raw else None
                reencrypted_memories, resumed = _reencrypt_memories_with_marker(
                    profile_name=profile.name,
                    old_key=vault.data_key,
                    new_key=resulting_data_key,
                    crash_after=crash_after,
                )

            # Memories are encrypted by `data_key`; in KEK-only rotation we must only rewrite
            # vault wrapping material and leave encrypted memory payloads untouched.
            salt, kek, wrapped = _build_wrapped_key_material(
                resulting_data_key, new_passphrase_resolved
            )
            Vault._write_secure(vault.salt_file, salt)
            Vault._write_secure(vault.key_file, wrapped)

            managed_uploaded = False
            if profile.mode == "managed":
                server_pubkey = get_secret("MATRIOSHA_VAULT_SERVER_PUBKEY")
                if not server_pubkey:
                    raise RuntimeError(
                        "MATRIOSHA_VAULT_SERVER_PUBKEY is required for managed key custody upload"
                    )

                sealed = double_wrap(resulting_data_key, kek, server_pubkey)

                async def _upload() -> None:
                    token = resolve_access_token(profile.name)
                    if not token:
                        raise RuntimeError(
                            "managed session token is required for managed key custody upload"
                        )
                    endpoint = profile.managed_endpoint or os.getenv("MATRIOSHA_MANAGED_ENDPOINT")
                    managed_client_cls = _vault_package_patchable("ManagedClient", ManagedClient)
                    upload_wrapped_key_fn = _vault_package_patchable(
                        "upload_wrapped_key", upload_wrapped_key
                    )
                    async with managed_client_cls(
                        token=token, base_url=endpoint, managed_mode=False
                    ) as client:
                        await upload_wrapped_key_fn(client, salt, sealed)
                        if rotate_data_key:
                            engine = SyncEngine(
                                local=LocalStore(profile.name),
                                remote=client,
                                embedder=get_default_embedder(),
                            )
                            await engine.sync()

                asyncio.run(_upload())
                managed_uploaded = True

            result = {
                "status": "ok",
                "profile": profile.name,
                "mode": profile.mode,
                "rotate_data_key": rotate_data_key,
                "reencrypted_memories": reencrypted_memories,
                "resumed": resumed,
                "managed_wrapped_key_uploaded": managed_uploaded,
            }

            if json_output:
                typer.echo(json.dumps(result))
            elif gctx.plain:
                typer.echo(f"profile: {profile.name}")
                typer.echo(f"mode: {profile.mode}")
                typer.echo(f"rotate_data_key: {str(rotate_data_key).lower()}")
                typer.echo(f"reencrypted_memories: {reencrypted_memories}")
                typer.echo(f"managed_wrapped_key_uploaded: {str(managed_uploaded).lower()}")
            else:
                _render_card(
                    "VAULT ROTATED",
                    [
                        ("profile", profile.name),
                        ("mode", profile.mode),
                        ("rotate key", str(rotate_data_key).lower()),
                        ("memories", str(reencrypted_memories)),
                        ("managed", str(managed_uploaded).lower()),
                    ],
                    status_chip="✓ ROTATED",
                    style="success",
                )

            raise typer.Exit(code=EXIT_OK)

        except RuntimeError as exc:
            if isinstance(exc, typer.Exit):
                raise
            if json_output:
                typer.echo(json.dumps({"status": "error", "error": str(exc)}))
            else:
                typer.echo(str(exc))
            raise typer.Exit(code=EXIT_USAGE)
