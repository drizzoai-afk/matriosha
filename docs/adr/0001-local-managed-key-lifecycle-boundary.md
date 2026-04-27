# ADR-0001: Keep local and managed key lifecycle boundaries explicit

## Status

Accepted

## Context

Matriosha has two operating modes with different trust boundaries.

Local mode is sovereign and offline-first. Users explicitly run `matriosha vault init` and manage passphrase, rotation, and export choices.

Managed mode is subscription-gated and should reduce key-management burden. After `matriosha auth login`, managed cryptographic custody is provisioned automatically and normal memory operations must not prompt users to manually generate keys or manage passphrases.

## Decision

Matriosha will keep local and managed key lifecycle behavior explicitly separated.

- `matriosha vault init` remains local-mode only.
- Managed first login is responsible for automatic key provisioning/custody.
- Managed memory, sync, token, and agent operations remain transparent after authentication.
- User-facing help and error text must not blur the two modes.

## Consequences

This protects local sovereignty while keeping managed UX simple. Tests and documentation should treat mode separation as a security boundary, not just a UX choice.
