# Matriosha

<p align="center">
  <strong>Hold AI accountable. Own your data.</strong>
</p>

<p align="center">
  <code>encrypted</code> · <code>auditable</code> · <code>model-agnostic</code> · <code>local-first</code>
</p>

<p align="center">
  <a href="https://pypi.org/project/matriosha/"><img alt="PyPI" src="https://img.shields.io/pypi/v/matriosha?style=flat-square&color=7c3aed"></a>
  <img alt="License" src="https://img.shields.io/badge/license-BSD--3--Clause-16a34a?style=flat-square">
</p>

<div align="center">

<pre>
███╗   ███╗ █████╗ ████████╗██████╗ ██╗ ██████╗ ███████╗██╗  ██╗ █████╗
████╗ ████║██╔══██╗╚══██╔══╝██╔══██╗██║██╔═══██╗██╔════╝██║  ██║██╔══██╗
██╔████╔██║███████║   ██║   ██████╔╝██║██║   ██║███████╗███████║███████║
██║╚██╔╝██║██╔══██║   ██║   ██╔══██╗██║██║   ██║╚════██║██╔══██║██╔══██║
██║ ╚═╝ ██║██║  ██║   ██║   ██║  ██║██║╚██████╔╝███████║██║  ██║██║  ██║
╚═╝     ╚═╝╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝
</pre>

</div>

**What it is**: Matriosha is a Python CLI for an **encrypted, auditable AI context engine**.

<p align="center">
  <img src="docs/assets/hero_no_args_typing.gif" alt="Matriosha command launcher" width="820">
</p>

## Why Matriosha?

**The problem**: AI agents are getting longer memories, but most memory systems are opaque, vendor-bound, or hard to verify.

**The approach**: Matriosha is built around three principles:

- **Model agnostic**: keep memory outside the model provider.
- **Encrypted by default**: your data is protected by hard math, not by mutable agreements.
- **Scalable when needed**: start local for free, then move to safe managed cloud if you need the peace of mind of not managing cryptographic keys. We store them in a separate encrypted vault, while your embeddings and vectors stay local and can be conveniently rebuilt.

## Quickstart

**Install**: Matriosha supports Python 3.11, 3.12, 3.13, and 3.14.

```bash
pip install matriosha
```

**Agent-assisted setup**: for interactive VM or local-machine setup, use the agent guide: [matriosha_agent_setup_guide.json](docs/assets/matriosha_agent_setup_guide.json)

**Initialize your encrypted local vault**:

```bash
matriosha vault init
```

**Remember a file**:

```bash
matriosha memory remember --file ~/Documents/agent-notes/launch-context.md
```

**Search semantically**:

```bash
matriosha memory search 'What is the launch motto'
```

**Verify vault integrity**:

```bash
matriosha vault verify
```

## Agent tokens

**Purpose**: Matriosha can issue local or managed tokens for desktop, server, and CI agents.

**Local agents**

**Use case**: encrypted memory should stay on your machine or VM.

- offline-first
- no authentication required
- uses the local vault
- token and agent commands use `--local`
- tokens can be time-limited with `--expires-in`

```bash
matriosha token generate my-agent --local --expires-in 30d
matriosha agent connect --local --name my-agent --kind desktop --token <token>
matriosha agent list --local
```

**Managed agents**

**Use case**: cloud-backed operational workflows for teams or production agents.

- sync
- policy
- quota
- billing
- token workflows
- agent workflows

```bash
matriosha auth login
matriosha token generate my-agent
matriosha agent connect --name my-agent --kind desktop --token <token>
matriosha agent list
```

**Token safety**: use real tokens carefully; they are the gate to your data.

### Verification workflow

**When to run**: after connecting agents or writing memory, verify the local audit trail and vault integrity.

```bash
matriosha audit verify
matriosha vault verify
matriosha vault verify --deep
```

## Encryption and auditability

- **Passphrase hardening**: Argon2id derives a 256-bit key from your passphrase.
- **Authenticated encryption**: AES-256-GCM protects vault data and detects tampering during decrypt.
- **Verifiable memory**: SHA-256 and Merkle roots support integrity checks for stored memories.
- **Audit trail**: local audit events can be verified independently with the audit workflow.
- **Signature-ready**: Ed25519 keypairs are available for signature workflows.

### Managed key custody

**Managed mode**: optional key custody for managed workflows.

- **Wrapped keys**: managed custody uses AES-GCM key wrapping.
- **Separated custody**: NaCl sealed boxes support server-side custody workflows.
- **Local-first fallback**: local mode can run without managed cloud custody.

## Pricing

**Local mode**: free, offline-first, and no authentication required.

- encrypted memory stays on your machine
- manual vault bootstrap with `matriosha vault init`
- local agent tokens use `--local`
- local verification uses `matriosha vault verify` and `matriosha audit verify`

```bash
matriosha mode set local
matriosha vault init
matriosha memory remember "hello from local mode" --tag demo
matriosha memory search "hello"
matriosha vault verify
```

**Managed mode**: €9/month for cloud-backed operational workflows.

- up to **3 agents**
- up to **3 GB** of managed storage
- sync
- policy
- quota
- billing
- token workflows
- agent workflows

```bash
matriosha mode set managed
matriosha auth login
matriosha billing status
matriosha memory remember "hello from managed mode" --tag demo
matriosha vault sync
```

**Billing commands**:

```bash
matriosha billing status
matriosha billing subscribe --agent-pack-count 1
matriosha billing upgrade
matriosha billing cancel --yes
```

**Upgrade path**: need more agents or storage? Use managed add-ons or upgrade paths as your deployment grows. The current CLI uses `--agent-pack-count 1` for the base managed plan.

## Requirements

- Python `>=3.11,<3.15`
- A Unix-like shell for the examples, such as Terminal on macOS, Linux shells, or WSL/Git Bash on Windows
- Optional system tools for rich file extraction, installed through `matriosha init` where supported

## Command map

**Top-level command groups**:

```text
matriosha
├── mode
├── profile
├── auth
├── billing
├── audit
├── quota
├── vault
├── memory
├── token
├── agent
├── status
├── doctor
├── compress
├── delete
└── init
```

**JSON output**:

```bash
matriosha --json memory search "contract renewal"
```

When `--json` is used, Matriosha keeps prompts and troubleshooting messages out of stdout so agents and scripts can parse the response safely.

## Information retrieval

**Structured recall**: Matriosha can return structured semantic envelopes for recalled files.

Built-in rich extraction targets common formats such as:

- text
- Markdown
- JSON
- CSV/TSV
- PDF
