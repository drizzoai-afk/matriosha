# ADR-0003: Use hash-chained audit events for tamper evidence

## Status

Accepted

## Context

Matriosha stores encrypted memory and supports integrity verification. Operational events such as memory writes, reads, deletes, key lifecycle changes, sync, and managed policy actions need a tamper-evident trail for troubleshooting and regulated review.

## Decision

Audit events should be append-only and hash-chained.

Each event should use canonical serialization with stable key ordering and include:

- an event timestamp,
- actor/workspace context when available,
- event type,
- safe event metadata,
- `prev_event_hash`,
- `event_hash`.

Correction must happen through compensating events, not in-place mutation.

## Consequences

Audit verification can recompute the chain and report structured diagnostics. This adds implementation discipline around canonical serialization, redaction, and retention/export workflows.
