"""Canonical Matriosha CLI command surface.

This module records the currently implemented and supported command surface.
Docs, launcher entries, and inventory tests must validate against this manifest.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandSpec:
    """Canonical metadata for one CLI command."""

    path: tuple[str, ...]
    description: str
    launcher_category: str | None = None
    launcher_label: str | None = None


COMMAND_SPECS: tuple[CommandSpec, ...] = (
    CommandSpec(("init",), "Check and install optional tools for available file formats.", "init", "init"),
    CommandSpec(("mode", "show"), "Show the active mode and profile.", "mode", "mode show"),
    CommandSpec(("mode", "set"), "Choose local mode or managed mode.", "mode", "mode set <local|managed>"),
    CommandSpec(("mode", "config", "get"), "Show mode configuration.", "mode", "mode config get"),
    CommandSpec(("mode", "config", "set"), "Update mode configuration.", "mode", "mode config set"),
    CommandSpec(("profile", "show"), "Show the selected profile and mode.", "profile", "profile show"),
    CommandSpec(("profile", "list"), "List saved profiles.", "profile", "profile list"),
    CommandSpec(("auth", "login"), "Log in to managed mode and set up managed encryption automatically.", "auth", "auth login"),
    CommandSpec(("auth", "logout"), "Log out of managed mode on this device.", "auth", "auth logout"),
    CommandSpec(("auth", "refresh"), "Refresh managed session tokens using the stored refresh token.", "auth", "auth refresh"),
    CommandSpec(("auth", "whoami"), "Show which managed account is logged in.", "auth", "auth whoami"),
    CommandSpec(("auth", "status"), "Alias for whoami, for script-friendly auth status checks.", "auth", "auth status"),
    CommandSpec(("auth", "switch"), "Switch to another workspace and use managed mode.", "auth", "auth switch"),
    CommandSpec(("billing", "status"), "View managed subscription status.", "billing", "billing status"),
    CommandSpec(("billing", "subscribe"), "Start a managed subscription.", "billing", "billing subscribe"),
    CommandSpec(("billing", "upgrade"), "Upgrade a managed subscription.", "billing", "billing upgrade"),
    CommandSpec(("billing", "cancel"), "Cancel a managed subscription.", "billing", "billing cancel"),
    CommandSpec(("quota", "status"), "Show storage use and plan limits.", "quota", "quota status"),
    CommandSpec(("vault", "init"), "Create or prepare an encrypted vault.", "vault", "vault init"),
    CommandSpec(("vault", "verify"), "Check vault integrity.", "vault", "vault verify"),
    CommandSpec(("vault", "rotate"), "Rotate vault encryption material.", "vault", "vault rotate"),
    CommandSpec(("vault", "export"), "Export encrypted vault data.", "vault", "vault export"),
    CommandSpec(("vault", "sync"), "Sync vault data in managed mode.", "vault", "vault sync"),
    CommandSpec(("memory", "remember"), "Save an encrypted memory.", "memory", "memory remember"),
    CommandSpec(("memory", "recall"), "Recall encrypted memories.", "memory", "memory recall"),
    CommandSpec(("memory", "search"), "Search encrypted memories.", "memory", "memory search"),
    CommandSpec(("memory", "list"), "List encrypted memories.", "memory", "memory list"),
    CommandSpec(("memory", "delete"), "Delete encrypted memories.", "memory", "memory delete"),
    CommandSpec(("memory", "compress"), "Compress similar memories.", "memory", "memory compress"),
    CommandSpec(("memory", "decompress"), "Decompress stored memory groups.", "memory", "memory decompress"),
    CommandSpec(("token", "generate"), "Create an access token for agents.", "token", "token generate"),
    CommandSpec(("token", "list"), "List access tokens.", "token", "token list"),
    CommandSpec(("token", "revoke"), "Revoke an access token.", "token", "token revoke"),
    CommandSpec(("token", "inspect"), "Inspect an access token.", "token", "token inspect"),
    CommandSpec(("agent", "connect"), "Connect an agent to Matriosha memory.", "agent", "agent connect"),
    CommandSpec(("agent", "list"), "List connected agents.", "agent", "agent list"),
    CommandSpec(("agent", "remove"), "Remove a connected agent.", "agent", "agent remove"),
    CommandSpec(("status",), "Show Matriosha setup and connection status.", "status", "status"),
    CommandSpec(("doctor",), "Check setup problems and suggest fixes.", "doctor", "doctor"),
    CommandSpec(("completion", "bash"), "Show Bash completion setup.", "completion", "completion bash"),
    CommandSpec(("completion", "zsh"), "Show Zsh completion setup.", "completion", "completion zsh"),
    CommandSpec(("completion", "fish"), "Show Fish completion setup.", "completion", "completion fish"),
    CommandSpec(("completion", "install"), "Install Terminal command suggestions.", "completion", "completion install"),
    CommandSpec(("compress",), "Reduce storage use by grouping similar memories.", "memory", "compress"),
    CommandSpec(("delete",), "Delete saved memories.", "memory", "delete"),
)


ROOT_COMMANDS: tuple[str, ...] = tuple(
    dict.fromkeys(spec.path[0] for spec in COMMAND_SPECS)
)


GROUP_COMMANDS: dict[str, tuple[str, ...]] = {
    group: tuple(
        dict.fromkeys(
            spec.path[1]
            for spec in COMMAND_SPECS
            if len(spec.path) > 1 and spec.path[0] == group
        )
    )
    for group in ROOT_COMMANDS
}


def launcher_commands() -> dict[str, list[tuple[str, list[str]]]]:
    """Return launcher command entries grouped by launcher category."""

    grouped: dict[str, list[tuple[str, list[str]]]] = {}
    for spec in COMMAND_SPECS:
        if spec.launcher_category is None or spec.launcher_label is None:
            continue
        grouped.setdefault(spec.launcher_category, []).append(
            (spec.launcher_label, list(spec.path))
        )
    return grouped
