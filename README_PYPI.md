# Matriosha

**Encrypted, auditable, model-agnostic, local-first AI memory for agents.**

Hold AI accountable. Own your data.

[![PyPI](https://img.shields.io/pypi/v/matriosha?style=flat-square&color=7c3aed)](https://pypi.org/project/matriosha/)
![Python](https://img.shields.io/pypi/pyversions/matriosha?style=flat-square)
![License](https://img.shields.io/badge/license-BSD--3--Clause-16a34a?style=flat-square)

## Install

Matriosha supports Python `3.11`, `3.12`, `3.13`, and `3.14`.

```bash
python3 -m pip install matriosha
```

If your environment already points `pip` to Python 3.11+, this also works:

```bash
pip install matriosha
```

## Quickstart

Initialize an encrypted local vault:

```bash
matriosha --mode local vault init
```

Remember text:

```bash
matriosha --mode local memory remember "Important launch context" --tag launch
```

Remember a file:

```bash
matriosha --mode local memory remember --file ~/Documents/agent-notes/launch-context.md --tag launch
```

Search semantically:

```bash
matriosha --mode local memory search "What is the launch motto?"
```

Verify the audit trail and vault integrity:

```bash
matriosha audit verify
matriosha vault verify
matriosha vault verify --deep
```

## Connect an agent locally

Generate a local-only token:

```bash
matriosha token generate my-agent --local --scope write --expires 30d
```

Connect a local desktop agent:

```bash
matriosha agent connect --local --name my-agent --kind desktop --token <token>
```

List local agents:

```bash
matriosha agent list --local
```

Treat generated tokens like passwords. Tokens are shown once.

## Optional custom vault location

Set `MATRIOSHA_HOME` before initializing a vault if you want a predictable local memory directory:

```bash
export MATRIOSHA_HOME=./memory
matriosha --mode local vault init
```

## Local and managed modes

Local mode is offline-first and does not require authentication.

Managed mode is optional and is designed for cloud-backed operational workflows such as login, workspace, sync, policy, quota, token workflows, and agent workflows.

```bash
matriosha auth login
matriosha --mode managed status
```

For local-only token and agent setup, use `--local` on token and agent commands.

## Why Matriosha?

AI agents are gaining longer memories, but many memory systems are opaque, vendor-bound, or difficult to verify.

Matriosha keeps AI context outside the model provider and makes it:

- **Encrypted**: vault data is protected with modern cryptography.
- **Auditable**: local audit events and vault integrity can be verified.
- **Model-agnostic**: memory is not tied to one AI vendor.
- **Local-first**: start offline, then opt into managed workflows when needed.
- **Agent-ready**: local, managed, desktop, server, and CI agent workflows are supported.

## Security model

- Argon2id passphrase hardening
- AES-256-GCM authenticated encryption
- SHA-256 and Merkle-root integrity checks
- Local audit verification
- Ed25519 signature-ready workflows
- Local-only tokens for local agent access

## Requirements

- Python `>=3.11,<3.15`
- A Unix-like shell for the examples, such as Terminal on macOS, Linux shells, or WSL/Git Bash on Windows

## Agent setup guide

For interactive VM or local-machine setup, use the public JSON guide:

- https://matriosha.in/assets/matriosha_agent_setup_guide.json

This guide is designed so AI agents can help users install, initialize, verify, and connect Matriosha safely.

## Project links

- Homepage: https://matriosha.in
- GitHub: https://github.com/drizzoai-afk/matriosha
- Issues: https://github.com/drizzoai-afk/matriosha/issues
- PyPI: https://pypi.org/project/matriosha/
- License: BSD 3-Clause
