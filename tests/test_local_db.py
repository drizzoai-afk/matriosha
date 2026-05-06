from __future__ import annotations

import subprocess

import pytest

from matriosha.core.local_db import (
    DEFAULT_LOCAL_DATABASE_URL,
    LocalDatabaseError,
    docker_available,
    ensure_default_local_pgvector,
    local_db_auto_start_enabled,
)


def test_local_db_auto_start_enabled_defaults_true(monkeypatch) -> None:
    monkeypatch.delenv("MATRIOSHA_LOCAL_DB_AUTO_START", raising=False)

    assert local_db_auto_start_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_local_db_auto_start_can_be_disabled(monkeypatch, value: str) -> None:
    monkeypatch.setenv("MATRIOSHA_LOCAL_DB_AUTO_START", value)

    assert local_db_auto_start_enabled() is False


def test_docker_available_false_when_binary_missing(monkeypatch) -> None:
    monkeypatch.setattr("matriosha.core.local_db.shutil.which", lambda _name: None)

    assert docker_available() is False


def test_ensure_default_local_pgvector_returns_default_when_auto_start_disabled(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MATRIOSHA_LOCAL_DB_AUTO_START", "0")

    assert ensure_default_local_pgvector() == DEFAULT_LOCAL_DATABASE_URL


def test_ensure_default_local_pgvector_fails_when_docker_missing(monkeypatch) -> None:
    monkeypatch.setenv("MATRIOSHA_LOCAL_DB_AUTO_START", "1")
    monkeypatch.setattr("matriosha.core.local_db.shutil.which", lambda _name: None)

    with pytest.raises(LocalDatabaseError, match="Docker is not installed"):
        ensure_default_local_pgvector()


def test_ensure_default_local_pgvector_starts_existing_container(monkeypatch) -> None:
    calls: list[list[str]] = []

    monkeypatch.setenv("MATRIOSHA_LOCAL_DB_AUTO_START", "1")
    monkeypatch.setattr("matriosha.core.local_db.shutil.which", lambda _name: "docker")

    def fake_run(args, **_kwargs):
        calls.append(list(args))
        if args[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(args, 0, stdout="24", stderr="")
        if args[:3] == ["docker", "container", "inspect"]:
            return subprocess.CompletedProcess(args, 0, stdout="{}", stderr="")
        if args[:2] == ["docker", "start"]:
            return subprocess.CompletedProcess(args, 0, stdout="matriosha-pgvector", stderr="")
        if args[:2] == ["docker", "exec"]:
            return subprocess.CompletedProcess(args, 0, stdout="accepting connections", stderr="")
        raise AssertionError(f"unexpected docker call: {args}")

    monkeypatch.setattr("matriosha.core.local_db.subprocess.run", fake_run)

    assert ensure_default_local_pgvector(timeout_seconds=1) == DEFAULT_LOCAL_DATABASE_URL
    assert ["docker", "start", "matriosha-pgvector"] in calls


def test_ensure_default_local_pgvector_creates_missing_container(monkeypatch) -> None:
    calls: list[list[str]] = []

    monkeypatch.setenv("MATRIOSHA_LOCAL_DB_AUTO_START", "1")
    monkeypatch.setattr("matriosha.core.local_db.shutil.which", lambda _name: "docker")

    def fake_run(args, **_kwargs):
        calls.append(list(args))
        if args[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(args, 0, stdout="24", stderr="")
        if args[:3] == ["docker", "container", "inspect"]:
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="not found")
        if args[:2] == ["docker", "run"]:
            return subprocess.CompletedProcess(args, 0, stdout="container-id", stderr="")
        if args[:2] == ["docker", "exec"]:
            return subprocess.CompletedProcess(args, 0, stdout="accepting connections", stderr="")
        raise AssertionError(f"unexpected docker call: {args}")

    monkeypatch.setattr("matriosha.core.local_db.subprocess.run", fake_run)

    assert ensure_default_local_pgvector(timeout_seconds=1) == DEFAULT_LOCAL_DATABASE_URL
    assert any(call[:2] == ["docker", "run"] for call in calls)
