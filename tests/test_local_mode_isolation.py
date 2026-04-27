from __future__ import annotations

import ast
from pathlib import Path


LOCAL_CORE_FILES = [
    Path("src/matriosha/core/storage_local.py"),
    Path("src/matriosha/core/vault.py"),
    Path("src/matriosha/core/local_tokens.py"),
]

DUAL_MODE_COMMAND_FILES = [
    *sorted(Path("src/matriosha/cli/commands/memory").glob("*.py")),
    *sorted(Path("src/matriosha/cli/commands/vault").glob("*.py")),
]

FORBIDDEN_CORE_IMPORT_PREFIXES = (
    "matriosha.api",
    "matriosha.core.managed",
    "matriosha.cli.commands.auth",
    "matriosha.cli.commands.billing",
    "matriosha.cli.commands.agent",
)

FORBIDDEN_CORE_IMPORT_NAMES = {
    "stripe",
    "supabase",
}


def _imports_from_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    imports: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)

    return imports


def test_local_core_files_exist() -> None:
    missing = [str(path) for path in LOCAL_CORE_FILES if not path.exists()]
    assert missing == []


def test_local_core_does_not_import_managed_api_auth_billing_or_agent_layers() -> None:
    violations: list[str] = []

    for path in LOCAL_CORE_FILES:
        for imported in _imports_from_file(path):
            if imported in FORBIDDEN_CORE_IMPORT_NAMES:
                violations.append(f"{path}: import {imported}")
            if imported.startswith(FORBIDDEN_CORE_IMPORT_PREFIXES):
                violations.append(f"{path}: import {imported}")

    assert violations == []


def test_local_core_does_not_reference_managed_environment_variables() -> None:
    forbidden_tokens = (
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_ANON_KEY",
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "MATRIOSHA_API_BASE_URL",
    )

    violations: list[str] = []

    for path in LOCAL_CORE_FILES:
        text = path.read_text()
        for token in forbidden_tokens:
            if token in text:
                violations.append(f"{path}: references {token}")

    assert violations == []


def test_memory_and_vault_commands_are_allowed_to_be_dual_mode_but_not_billing_or_agent_commands() -> None:
    """Memory/vault commands may support managed mode, but must not become billing/agent command wrappers."""

    forbidden_command_import_prefixes = (
        "matriosha.cli.commands.billing",
        "matriosha.cli.commands.agent",
    )

    violations: list[str] = []

    for path in DUAL_MODE_COMMAND_FILES:
        for imported in _imports_from_file(path):
            if imported.startswith(forbidden_command_import_prefixes):
                violations.append(f"{path}: import {imported}")

    assert violations == []
