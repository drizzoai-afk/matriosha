# ADR-0002: Treat CLI JSON output as a machine-readable contract

## Status

Accepted

## Context

Matriosha is used by humans and agents. Agents depend on stable `--json` output for recall, search, diagnostics, billing, and automation. Prompts, progress text, and troubleshooting messages can break automation if mixed into JSON stdout.

## Decision

CLI JSON output is a compatibility contract.

- JSON-mode command stdout must remain machine-readable.
- Human prompts and passphrase prompts must not corrupt JSON stdout.
- Errors should include stable fields such as `status`, `category`, `code`, `exit`, `fix`, and safe diagnostics.
- Sensitive values must be redacted before reaching JSON output, logs, or tracebacks.

## Consequences

Future commands must be tested in JSON mode. Debug detail is allowed only when it is structured and safe. Human rendering can evolve independently, but JSON schemas should change only intentionally.
