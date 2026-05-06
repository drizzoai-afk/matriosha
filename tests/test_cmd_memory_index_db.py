from __future__ import annotations

from typer.testing import CliRunner

from matriosha.cli.main import app

runner = CliRunner()


def test_memory_help_shows_index_db_commands() -> None:
    result = runner.invoke(app, ["memory", "--help"])

    assert result.exit_code == 0
    assert "index-status" in result.output
    assert "index-start" in result.output
    assert "index-env" in result.output


def test_memory_index_env_outputs_exports() -> None:
    result = runner.invoke(app, ["--plain", "memory", "index-env"])

    assert result.exit_code == 0
    assert "export MATRIOSHA_LOCAL_VECTOR_BACKEND=pgvector" in result.output
    assert "export MATRIOSHA_LOCAL_DATABASE_URL=" in result.output
    assert "export MATRIOSHA_LOCAL_DB_AUTO_START=1" in result.output


def test_memory_index_status_json(monkeypatch) -> None:
    monkeypatch.setenv("MATRIOSHA_LOCAL_VECTOR_BACKEND", "pgvector")
    monkeypatch.setattr("matriosha.cli.commands.memory.index_db.docker_available", lambda: False)

    result = runner.invoke(app, ["--json", "memory", "index-status"])

    assert result.exit_code == 0
    assert '"backend_env": "pgvector"' in result.output
    assert '"docker_available": false' in result.output
    assert '"container_status": "docker-unavailable"' in result.output


def test_memory_index_start_json_success(monkeypatch) -> None:
    monkeypatch.setattr(
        "matriosha.cli.commands.memory.index_db.ensure_default_local_pgvector",
        lambda timeout_seconds=30.0: "postgresql://matriosha:matriosha@localhost:5432/matriosha",
    )

    result = runner.invoke(app, ["--json", "memory", "index-start"])

    assert result.exit_code == 0
    assert '"ok": true' in result.output
    assert '"container": "matriosha-pgvector"' in result.output


def test_memory_index_start_json_failure(monkeypatch) -> None:
    from matriosha.core.local_db import LocalDatabaseError

    def fail_start(timeout_seconds=30.0) -> str:
        raise LocalDatabaseError("Docker is not installed")

    monkeypatch.setattr(
        "matriosha.cli.commands.memory.index_db.ensure_default_local_pgvector", fail_start
    )

    result = runner.invoke(app, ["--json", "memory", "index-start"])

    assert result.exit_code == 10
    assert '"ok": false' in result.output
    assert "Docker is not installed" in result.output
