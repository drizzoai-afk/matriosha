"""Vault sync command."""

from __future__ import annotations

from .common import *

def _compat_symbol(name: str):
    """Read package-level symbols so legacy tests/monkeypatches keep working."""
    import matriosha.cli.commands.vault as vault_package

    return getattr(vault_package, name, globals()[name])


def register(app: typer.Typer) -> None:
    def _emit_sync_report(report: SyncReport, *, json_output: bool, plain: bool, console: Console) -> None:
        payload = report.to_dict()
        payload["status"] = "ok" if not report.errors else "error"

        if json_output:
            typer.echo(json.dumps(payload))
            return

        if plain:
            typer.echo(f"pushed: {report.pushed}")
            typer.echo(f"pulled: {report.pulled}")
            typer.echo(f"warnings: {len(report.warnings)}")
            typer.echo(f"errors: {len(report.errors)}")
            for warning in report.warnings:
                typer.echo(f"warning: {warning}")
            for error in report.errors:
                typer.echo(f"error: {error}")
            return

        table = Table(title="Vault Sync Report", show_header=True, header_style="bold accent")
        table.add_column("metric")
        table.add_column("value", justify="right")
        table.add_row("pushed", str(report.pushed))
        table.add_row("pulled", str(report.pulled))
        table.add_row("warnings", str(len(report.warnings)))
        table.add_row("errors", str(len(report.errors)))
        console.print(table)

        if report.warnings:
            warning_table = Table(title="Sync Warnings", show_header=True, header_style="bold warning")
            warning_table.add_column("warning")
            for warning in report.warnings:
                warning_table.add_row(warning)
            console.print(warning_table)

        if report.errors:
            error_table = Table(title="Sync Errors", show_header=True, header_style="bold danger")
            error_table.add_column("error")
            for error in report.errors:
                error_table.add_row(error)
            console.print(error_table)


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


    @app.command("sync")
    def sync(
        ctx: typer.Context,
        watch: int | None = typer.Option(
            None,
            "--watch",
            min=1,
            help="Continuously sync every INTERVAL seconds.",
        ),
        json_output_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
    ) -> None:
        """Synchronize local encrypted memories with managed storage."""

        require_mode("managed")(ctx)

        gctx = get_global_context(ctx)
        json_output = gctx.json_output or json_output_flag
        console = make_console()

        signal_module = _compat_symbol("signal")
        managed_client_cls = _compat_symbol("ManagedClient")
        sync_engine_cls = _compat_symbol("SyncEngine")

        cfg = load_config()
        profile = get_active_profile(cfg, gctx.profile)

        token = resolve_access_token(profile.name)
        if not token:
            _emit_error(
                title="Managed token missing",
                category="AUTH",
                stable_code="AUTH-211",
                exit_code=EXIT_AUTH,
                fix="run `matriosha auth login` or set MATRIOSHA_MANAGED_TOKEN",
                debug="managed session token unavailable",
                json_output=json_output,
                plain=gctx.plain,
            )
            raise typer.Exit(code=EXIT_AUTH)

        endpoint = profile.managed_endpoint or os.getenv("MATRIOSHA_MANAGED_ENDPOINT")

        async def _run_sync() -> SyncReport:
            async with managed_client_cls(token=token, base_url=endpoint, managed_mode=False) as client:
                try:
                    await client.whoami()
                except Exception as exc:  # noqa: BLE001
                    raise RuntimeError(f"managed token validation failed: {type(exc).__name__}: {exc}") from exc

                engine = sync_engine_cls(local=LocalStore(profile.name), remote=client, embedder=get_default_embedder())
                return await engine.sync()

        def _run_single_iteration() -> SyncReport:
            if json_output or gctx.plain:
                return asyncio.run(_run_sync())

            with Progress(
                SpinnerColumn(),
                TextColumn("[bold cyan]{task.description}"),
                BarColumn(),
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("vault sync", total=3)
                progress.update(task, description="[bold cyan]validating managed session")
                progress.advance(task)
                progress.update(task, description="[bold cyan]syncing memories")
                report = asyncio.run(_run_sync())
                progress.advance(task, advance=2)
                return report

        watch_interval = watch
        if watch_interval is None:
            try:
                report = _run_single_iteration()
            except RuntimeError as exc:
                _emit_error(
                    title="Managed sync failed",
                    category="AUTH",
                    stable_code="AUTH-212",
                    exit_code=EXIT_AUTH,
                    fix="refresh managed credentials and retry",
                    debug=str(exc),
                    json_output=json_output,
                    plain=gctx.plain,
                )
                raise typer.Exit(code=EXIT_AUTH)

            _emit_sync_report(report, json_output=json_output, plain=gctx.plain, console=console)
            if report.errors:
                raise typer.Exit(code=EXIT_INTEGRITY)
            raise typer.Exit(code=EXIT_OK)

        stop_requested = False

        def _sigint_handler(signum, frame) -> None:  # noqa: ANN001,ARG001
            nonlocal stop_requested
            stop_requested = True
            logger.info("vault sync watch received SIGINT; stopping after current iteration")

        previous_handler = signal_module.getsignal(signal_module.SIGINT)
        signal_module.signal(signal_module.SIGINT, _sigint_handler)

        iteration = 0
        try:
            while True:
                iteration += 1
                logger.info("vault sync watch iteration=%s started", iteration)

                try:
                    report = _run_single_iteration()
                    _emit_sync_report(report, json_output=json_output, plain=gctx.plain, console=console)
                    logger.info(
                        "vault sync watch iteration=%s complete pushed=%s pulled=%s errors=%s",
                        iteration,
                        report.pushed,
                        report.pulled,
                        len(report.errors),
                    )
                except RuntimeError as exc:
                    debug = str(exc)
                    logger.warning("vault sync watch iteration=%s failed: %s", iteration, debug)
                    if json_output:
                        typer.echo(json.dumps({"status": "error", "iteration": iteration, "error": debug}))
                    elif gctx.plain:
                        typer.echo(f"iteration {iteration} error: {debug}")
                    else:
                        typer.echo(f"[watch] iteration {iteration} error: {debug}")
                except Exception as exc:  # noqa: BLE001
                    debug = f"{type(exc).__name__}: {exc}"
                    logger.warning("vault sync watch iteration=%s unexpected failure: %s", iteration, debug)
                    if json_output:
                        typer.echo(json.dumps({"status": "error", "iteration": iteration, "error": debug}))
                    elif gctx.plain:
                        typer.echo(f"iteration {iteration} error: {debug}")
                    else:
                        typer.echo(f"[watch] iteration {iteration} error: {debug}")

                if stop_requested:
                    break

                slept = 0
                while slept < watch_interval and not stop_requested:
                    time.sleep(1)
                    slept += 1

            raise typer.Exit(code=EXIT_OK)
        finally:
            signal_module.signal(signal_module.SIGINT, previous_handler)

