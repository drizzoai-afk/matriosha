# Matriosha

**Matriosha is a Python CLI for an encrypted, auditable AI context engine.**

Hold AI accountable. Own your data.

[![PyPI](https://img.shields.io/pypi/v/matriosha?style=flat-square&color=7c3aed)](https://pypi.org/project/matriosha/)
![Python](https://img.shields.io/pypi/pyversions/matriosha?style=flat-square)
![License](https://img.shields.io/badge/license-BSD--3--Clause-16a34a?style=flat-square)

## Install

Matriosha supports Python `3.11`, `3.12`, `3.13`, and `3.14`.

    pip install matriosha

## Quickstart

Initialize an encrypted local vault:

    matriosha vault init

Remember text:

    matriosha memory remember "Important launch context" --tag launch

Remember a file:

    matriosha memory remember --file ~/Documents/agent-notes/launch-context.md

Search semantically:

    matriosha memory search "What is the launch motto?"

Verify vault integrity:

    matriosha vault verify

## Why Matriosha?

AI agents are gaining longer memories, but many memory systems are opaque, vendor-bound, or difficult to verify.

Matriosha keeps AI context outside the model provider and makes it:

- **Encrypted**: vault data is protected with modern cryptography.
- **Auditable**: local audit events and vault integrity can be verified.
- **Model-agnostic**: memory is not tied to one AI vendor.
- **Local-first**: start offline, then opt into managed workflows when needed.

## Local and managed modes

Local mode is free, offline-first, and does not require authentication.

Managed mode is designed for cloud-backed operational workflows such as sync, policy, quota, billing, token workflows, and agent workflows.

## Requirements

- Python `>=3.11,<3.15`
- A Unix-like shell for the examples, such as Terminal on macOS, Linux shells, or WSL/Git Bash on Windows

## Core commands

    matriosha vault init
    matriosha memory remember "hello from local mode" --tag demo
    matriosha memory search "hello"
    matriosha audit verify
    matriosha vault verify
    matriosha vault verify --deep
    matriosha token generate my-agent --local --expires-in 30d
    matriosha agent connect --local --name my-agent --kind desktop --token <token>
    matriosha agent list --local

## Security model

- Argon2id passphrase hardening
- AES-256-GCM authenticated encryption
- SHA-256 and Merkle-root integrity checks
- Local audit verification
- Ed25519 signature-ready workflows

## Project links

- Homepage: https://github.com/drizzoai-afk/matriosha
- Issues: https://github.com/drizzoai-afk/matriosha/issues
- License: BSD 3-Clause
