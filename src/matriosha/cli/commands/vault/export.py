"""Vault export command."""

from __future__ import annotations

import io
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path

import typer

from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_OK
from matriosha.core.binary_protocol import envelope_to_json, merkle_root
from matriosha.core.config import get_active_profile, load_config
from matriosha.core.storage_local import LocalStore

from .common import _render_card

def register(app: typer.Typer) -> None:
    def _default_export_path(profile_name: str) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return Path.cwd() / f"matriosha-{profile_name}-{stamp}.tar.gz"


    def _build_export_archive(profile_name: str, mode: str, output_path: Path) -> dict[str, object]:
        store = LocalStore(profile_name)
        envelopes = sorted(store.list(limit=1_000_000), key=lambda item: item.memory_id)

        envelope_index: list[dict[str, object]] = []
        memory_roots: list[str] = []
        memory_entries: list[dict[str, str]] = []

        for env in envelopes:
            env_file = store.root / "memories" / f"{env.memory_id}.env.json"
            payload_file = store.root / "memories" / f"{env.memory_id}.bin.b64"
            if not env_file.exists() or not payload_file.exists():
                continue

            envelope_index.append(json.loads(envelope_to_json(env)))
            memory_roots.append(env.merkle_root)
            memory_entries.append(
                {
                    "memory_id": env.memory_id,
                    "envelope": f"memories/{env_file.name}",
                    "payload": f"memories/{payload_file.name}",
                }
            )

        manifest = {
            "profile": profile_name,
            "mode": mode,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "memory_count": len(memory_entries),
            "memory_merkle_roots": memory_roots,
            "merkle_root": merkle_root(memory_roots),
            "encoding": "base64",
            "hash_algo": "sha256",
        }

        output_path.parent.mkdir(parents=True, exist_ok=True)

        with tarfile.open(output_path, "w:gz") as archive:
            for entry in memory_entries:
                archive.add(store.root / entry["envelope"], arcname=entry["envelope"])
                archive.add(store.root / entry["payload"], arcname=entry["payload"])

            index_bytes = json.dumps(envelope_index, separators=(",", ":"), sort_keys=True).encode("utf-8")
            manifest_bytes = json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode("utf-8")
            memories_bytes = json.dumps(memory_entries, separators=(",", ":"), sort_keys=True).encode("utf-8")

            for arcname, blob in (
                ("envelope_index.json", index_bytes),
                ("manifest.json", manifest_bytes),
                ("memories_index.json", memories_bytes),
            ):
                info = tarfile.TarInfo(name=arcname)
                info.size = len(blob)
                info.mode = 0o600
                archive.addfile(info, io.BytesIO(blob))

        return {
            "path": str(output_path),
            "memory_count": len(memory_entries),
            "merkle_root": manifest["merkle_root"],
        }


    @app.command("export")
    def export(
        ctx: typer.Context,
        out: Path | None = typer.Option(None, "--out", help="Output .tar.gz path for export archive."),
        json_output_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
    ) -> None:
        """Export local encrypted memories to tar.gz with archive manifest integrity."""

        gctx = get_global_context(ctx)
        json_output = gctx.json_output or json_output_flag

        cfg = load_config()
        profile = get_active_profile(cfg, gctx.profile)
        target = out or _default_export_path(profile.name)

        result = _build_export_archive(profile.name, profile.mode, target)

        if json_output:
            typer.echo(json.dumps(result))
        elif gctx.plain:
            typer.echo(f"export: {result['path']}")
            typer.echo(f"memories: {result['memory_count']}")
            typer.echo(f"merkle_root: {result['merkle_root']}")
        else:
            _render_card(
                "VAULT EXPORT",
                [
                    ("path", str(result["path"])),
                    ("memories", str(result["memory_count"])),
                    ("merkle", str(result["merkle_root"])),
                ],
                status_chip="✓ EXPORTED",
                style="success",
            )

        raise typer.Exit(code=EXIT_OK)

