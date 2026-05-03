"""Local PostgreSQL/pgvector bootstrap helpers.

Matriosha uses a local-only PostgreSQL/pgvector database for production semantic
retrieval. This module can automatically create/start the default Docker
container when Docker is already installed.

It intentionally does not install Docker automatically.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time

DEFAULT_LOCAL_DB_CONTAINER = "matriosha-pgvector"
DEFAULT_LOCAL_DB_IMAGE = "pgvector/pgvector:pg16"
LOCAL_DB_IMAGE_ENV = "MATRIOSHA_LOCAL_DB_IMAGE"
DEFAULT_LOCAL_DB_VOLUME = "matriosha_pgvector_data"
DEFAULT_LOCAL_DB_USER = "matriosha"
DEFAULT_LOCAL_DB_PASSWORD = "matriosha"
DEFAULT_LOCAL_DB_NAME = "matriosha"
DEFAULT_LOCAL_DB_PORT = 5432
DEFAULT_LOCAL_DATABASE_URL = (
    f"postgresql://{DEFAULT_LOCAL_DB_USER}:{DEFAULT_LOCAL_DB_PASSWORD}"
    f"@localhost:{DEFAULT_LOCAL_DB_PORT}/{DEFAULT_LOCAL_DB_NAME}"
)

LOCAL_DB_AUTO_START_ENV = "MATRIOSHA_LOCAL_DB_AUTO_START"


class LocalDatabaseError(RuntimeError):
    """Raised when the local pgvector database cannot be prepared."""


def local_db_auto_start_enabled() -> bool:
    raw = os.getenv(LOCAL_DB_AUTO_START_ENV, "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def get_local_db_image() -> str:
    """Return the Docker image used for Matriosha's default local vector database."""
    return os.getenv(LOCAL_DB_IMAGE_ENV, DEFAULT_LOCAL_DB_IMAGE).strip() or DEFAULT_LOCAL_DB_IMAGE


def docker_available() -> bool:
    docker = shutil.which("docker")
    if not docker:
        return False
    try:
        result = subprocess.run(
            [docker, "version", "--format", "{{.Server.Version}}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return False
    return result.returncode == 0


def ensure_default_local_pgvector(*, timeout_seconds: float = 30.0) -> str:
    """Ensure the default local pgvector Docker container is running.

    Returns the default local database URL.

    Docker must already be installed and running.
    """

    if not local_db_auto_start_enabled():
        return DEFAULT_LOCAL_DATABASE_URL

    docker = shutil.which("docker")
    if not docker:
        raise LocalDatabaseError(
            "Docker is not installed. Install Docker, then rerun this command, "
            "or set MATRIOSHA_LOCAL_DATABASE_URL to your own local PostgreSQL/pgvector database."
        )

    if not docker_available():
        raise LocalDatabaseError(
            "Docker is installed but not running/reachable. Start Docker, then rerun this command, "
            "or set MATRIOSHA_LOCAL_DATABASE_URL to your own local PostgreSQL/pgvector database."
        )

    container_exists = _docker_container_exists(docker, DEFAULT_LOCAL_DB_CONTAINER)
    if container_exists:
        _docker_start_container(docker, DEFAULT_LOCAL_DB_CONTAINER)
    else:
        _docker_create_container(docker)

    _wait_for_container_ready(docker, timeout_seconds=timeout_seconds)
    return DEFAULT_LOCAL_DATABASE_URL


def _docker_container_exists(docker: str, name: str) -> bool:
    result = subprocess.run(
        [docker, "container", "inspect", name],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.returncode == 0


def _docker_start_container(docker: str, name: str) -> None:
    result = subprocess.run(
        [docker, "start", name],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode != 0 and "is already running" not in result.stderr.lower():
        raise LocalDatabaseError(f"failed to start Docker container {name}: {result.stderr.strip()}")


def _docker_create_container(docker: str) -> None:
    result = subprocess.run(
        [
            docker,
            "run",
            "--name",
            DEFAULT_LOCAL_DB_CONTAINER,
            "-e",
            f"POSTGRES_USER={DEFAULT_LOCAL_DB_USER}",
            "-e",
            f"POSTGRES_PASSWORD={DEFAULT_LOCAL_DB_PASSWORD}",
            "-e",
            f"POSTGRES_DB={DEFAULT_LOCAL_DB_NAME}",
            "-p",
            f"{DEFAULT_LOCAL_DB_PORT}:5432",
            "-v",
            f"{DEFAULT_LOCAL_DB_VOLUME}:/var/lib/postgresql/data",
            "-d",
            get_local_db_image(),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise LocalDatabaseError(f"failed to create Docker pgvector container: {result.stderr.strip()}")


def _wait_for_container_ready(docker: str, *, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""

    while time.monotonic() < deadline:
        result = subprocess.run(
            [
                docker,
                "exec",
                DEFAULT_LOCAL_DB_CONTAINER,
                "pg_isready",
                "-U",
                DEFAULT_LOCAL_DB_USER,
                "-d",
                DEFAULT_LOCAL_DB_NAME,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return
        last_error = (result.stdout + result.stderr).strip()
        time.sleep(0.5)

    raise LocalDatabaseError(f"local pgvector database did not become ready within {timeout_seconds:.0f}s: {last_error}")
