"""Memory command group with Phase 2.6 `remember` implementation."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import typer
from rich.console import Console

from cli.utils.context import get_global_context
from cli.utils.errors import EXIT_AUTH, EXIT_INTEGRITY, EXIT_UNKNOWN, EXIT_USAGE
from core.binary_protocol import encode_envelope
from core.config import get_active_profile, load_config
from core.crypto import IntegrityError
from core.storage_local import LocalStore
from core.vault import AuthError, Vault, VaultIntegrityError

app = typer.Typer(help="Encrypted memory operations.", no_args_is_help=True)

_MAX_MEMORY_BYTES = 50 * 1024 * 1024
_TAG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,31}$")


class InvalidInput(ValueError):
    """Raised when command input does not satisfy the command contract."""


def _short(value: str, *, head: int = 8, tail: int = 4) -> str:
    if len(value) <= head + tail + 1:
        return value
    return f"{value[:head]}…{value[-tail:]}"


def _render_panel(
    title: str,
    rows: list[tuple[str, str]],
    *,
    status_chip: str,
    style: str,
    console: Console,
) -> None:
    width = 88
    inner = width - 2
    header = f" {status_chip} {title} "
    header_pad = max(0, inner - len(header))
    console.print(
        f"[{style}]╭{'─' * (header_pad // 2)}{header}{'─' * (header_pad - header_pad // 2)}╮[/{style}]"
    )
    for key, value in rows:
        line = f" {key:<10} {value} "
        console.print(f"[{style}]│{line:<{inner}}│[/{style}]")
    console.print(f"[{style}]╰{'─' * inner}╯[/{style}]")


def _emit_error(
    *,
    title: str,
    category: str,
    stable_code: str,
    exit_code: int,
    fix: str,
    debug: str,
    json_output: bool,
    plain: bool,
    console: Console,
) -> None:
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "status": "error",
                    "title": title,
                    "category": category,
                    "code": stable_code,
                    "exit": exit_code,
                    "fix": fix,
                    "debug": debug,
                }
            )
        )
    elif plain:
        typer.echo(f"{title}")
        typer.echo(f"category: {category}  code: {stable_code}  exit: {exit_code}")
        typer.echo(f"fix: {fix}")
        typer.echo(f"debug: {debug}")
    else:
        _render_panel(
            title,
            [
                ("category", f"{category}  code: {stable_code}  exit: {exit_code}"),
                ("fix", fix),
                ("debug", debug),
            ],
            status_chip="✖ ERROR",
            style="red",
            console=console,
        )


def _resolve_payload_bytes(*, text: str | None, file_path: Path | None, stdin_input: bool) -> bytes:
    selected = int(text is not None) + int(file_path is not None) + int(stdin_input)
    if selected != 1:
        raise InvalidInput("provide exactly one input source: TEXT or --file or --stdin")

    if text is not None:
        payload = text.encode("utf-8")
    elif file_path is not None:
        if not file_path.exists() or not file_path.is_file():
            raise InvalidInput(f"file not found: {file_path}")
        payload = file_path.read_bytes()
    else:
        payload = sys.stdin.buffer.read()

    if len(payload) > _MAX_MEMORY_BYTES:
        raise InvalidInput("input exceeds max size of 50 MiB")

    return payload


def _validate_tags(tags: list[str]) -> list[str]:
    normalized = []
    for tag in tags:
        if not _TAG_PATTERN.fullmatch(tag):
            raise InvalidInput(
                f"invalid tag '{tag}'. expected regex: ^[a-z0-9][a-z0-9_\\-]{{0,31}}$"
            )
        normalized.append(tag)
    return normalized


def _resolve_passphrase() -> str:
    env_passphrase = os.getenv("MATRIOSHA_PASSPHRASE")
    if env_passphrase:
        return env_passphrase
    return typer.prompt("Vault passphrase", hide_input=True)


@app.command("remember")
def remember(
    ctx: typer.Context,
    text: str | None = typer.Argument(None, help="Text to store as encrypted memory."),
    file_path: Path | None = typer.Option(None, "--file", help="Read memory payload from file."),
    tags: list[str] = typer.Option([], "--tag", help="Attach one or more lowercase tags."),
    stdin_input: bool = typer.Option(False, "--stdin", help="Read memory payload from stdin."),
    json_output_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Store encrypted memory into the local profile store."""

    gctx = get_global_context(ctx)
    json_output = gctx.json_output or json_output_flag
    console = Console()

    try:
        payload = _resolve_payload_bytes(text=text, file_path=file_path, stdin_input=stdin_input)
        validated_tags = _validate_tags(tags)

        cfg = load_config()
        profile = get_active_profile(cfg, gctx.profile)
        active_mode = profile.mode

        if stdin_input and (not json_output) and (not gctx.plain):
            console.print("[cyan]● READING STDIN[/cyan]")

        vault = Vault.unlock(profile.name, _resolve_passphrase())
        env, b64_payload = encode_envelope(
            payload,
            vault.data_key,
            mode=active_mode,
            tags=validated_tags,
            source="cli",
        )

        store = LocalStore(profile.name)
        path = store.put(env, b64_payload)

        result = {
            "memory_id": env.memory_id,
            "bytes": len(payload),
            "blocks": len(env.merkle_leaves),
            "merkle_root": env.merkle_root,
            "tags": validated_tags,
            "path": str(path),
        }

        if json_output:
            typer.echo(json.dumps(result))
        elif gctx.plain:
            typer.echo(f"memory stored: {env.memory_id}")
            typer.echo(f"bytes: {len(payload)}")
            typer.echo(f"blocks: {len(env.merkle_leaves)}")
            typer.echo(f"merkle_root: {env.merkle_root}")
            typer.echo(f"tags: {', '.join(validated_tags) if validated_tags else '-'}")
        else:
            rendered_tags = " ".join(f"#{tag}" for tag in validated_tags) if validated_tags else "-"
            _render_panel(
                "MEMORY STORED",
                [
                    ("id", _short(env.memory_id, head=12, tail=6)),
                    ("bytes", f"{len(payload):,}"),
                    ("blocks", str(len(env.merkle_leaves))),
                    ("merkle", _short(env.merkle_root, head=12, tail=6)),
                    ("tags", rendered_tags),
                ],
                status_chip="✓ SUCCESS",
                style="green",
                console=console,
            )

        return

    except InvalidInput as exc:
        _emit_error(
            title="Invalid remember input",
            category="VAL",
            stable_code="VAL-001",
            exit_code=EXIT_USAGE,
            fix="provide exactly one source and valid tags; keep input <= 50 MiB",
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
            fix="set MATRIOSHA_PASSPHRASE correctly or retry with the right passphrase",
            debug="provider=local_vault profile_auth_failed",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_AUTH)
    except IntegrityError:
        _emit_error(
            title="Memory encoding integrity failure",
            category="SYS",
            stable_code="SYS-010",
            exit_code=EXIT_INTEGRITY,
            fix="retry the command; if persistent run `matriosha vault verify`",
            debug="phase=encode_envelope integrity_check_failed",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_INTEGRITY)
    except (VaultIntegrityError, OSError, ValueError) as exc:
        _emit_error(
            title="Local storage operation failed",
            category="STORE",
            stable_code="STORE-001",
            exit_code=EXIT_UNKNOWN,
            fix="check file permissions and available disk, then retry",
            debug=f"os_error={type(exc).__name__}",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_UNKNOWN)
    except Exception as exc:  # noqa: BLE001
        _emit_error(
            title="Unexpected remember failure",
            category="SYS",
            stable_code="SYS-999",
            exit_code=EXIT_UNKNOWN,
            fix="retry with --debug and run `matriosha doctor`",
            debug=f"exception={type(exc).__name__}",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_UNKNOWN)


@app.command("recall")
def recall(ctx: typer.Context) -> None:
    """Stub for `memory recall`."""
    _ = get_global_context(ctx)
    typer.echo("not implemented in phase 1")
    raise typer.Exit(code=EXIT_UNKNOWN)


@app.command("search")
def search(ctx: typer.Context) -> None:
    """Stub for `memory search`."""
    _ = get_global_context(ctx)
    typer.echo("not implemented in phase 1")
    raise typer.Exit(code=EXIT_UNKNOWN)


@app.command("list")
def list_memories(ctx: typer.Context) -> None:
    """Stub for `memory list`."""
    _ = get_global_context(ctx)
    typer.echo("not implemented in phase 1")
    raise typer.Exit(code=EXIT_UNKNOWN)


@app.command("delete")
def delete(ctx: typer.Context) -> None:
    """Stub for `memory delete`."""
    _ = get_global_context(ctx)
    typer.echo("not implemented in phase 1")
    raise typer.Exit(code=EXIT_UNKNOWN)


@app.command("compress")
def compress(ctx: typer.Context) -> None:
    """Stub for `memory compress`."""
    _ = get_global_context(ctx)
    typer.echo("not implemented in phase 1")
    raise typer.Exit(code=EXIT_UNKNOWN)


@app.command("decompress")
def decompress(ctx: typer.Context) -> None:
    """Stub for `memory decompress`."""
    _ = get_global_context(ctx)
    typer.echo("not implemented in phase 1")
    raise typer.Exit(code=EXIT_UNKNOWN)
