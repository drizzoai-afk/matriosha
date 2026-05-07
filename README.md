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

**The problem**: AI agents are getting longer memories, but most memory systems are opaque, vendor-bound, overexposed, or hard to verify.

**The approach**: Matriosha is built around three principles:

- **Model agnostic**: keep memory outside the model provider, so your AI context can move across agents, models, and applications.
- **Token efficient**: expose the agent or AI application only to the data it actually needs, reducing unnecessary context, token use, and data treatment.
- **Secure**: run zero-knowledge local memory by default, while enabling optional managed key custody for convenient and safe access from anywhere.

## Who it is for

Matriosha is designed for:

- AI developers building long-memory agents
- local-first and privacy-focused workflows
- CI and operational automation
- multi-agent orchestration systems
- teams that need auditable AI context handling

## Quickstart: local encrypted memory

Matriosha starts local. No account is required, and your encrypted memory stays on your machine.

### Agent or LLM-assisted setup

For a simpler and interactive setup, use the agent guide: [matriosha_agent_setup_guide.json](docs/assets/matriosha_agent_setup_guide.json)

### Install

Matriosha supports Python 3.11, 3.12, 3.13, and 3.14.

```bash
pip install matriosha
```

If your environment uses `python3` and `pip3`, use:

```bash
python3 -m pip install matriosha
```

### Choose where the encrypted vault lives

By default, Matriosha uses your operating system's standard app data and config directories.

For a project-local memory root, set `MATRIOSHA_HOME`:

```bash
export MATRIOSHA_HOME=./memory
```

With this setting, Matriosha stores data and config under:

```text
./memory/data
./memory/config
```

For the default profile, encrypted memory files live under:

```text
./memory/data/default/memories
```

You can also override data and config separately:

```bash
export MATRIOSHA_DATA_DIR=./memory-data
export MATRIOSHA_CONFIG_DIR=./memory-config
```

Specific overrides win over `MATRIOSHA_HOME`.

### Select local mode

```bash
matriosha mode set local
```

### Initialize the encrypted local vault

```bash
matriosha vault init
```

Matriosha creates the local encrypted vault and asks for the vault passphrase when required.

### Save your first memory

Save inline text:

```bash
matriosha memory remember "Matriosha keeps AI memory encrypted, auditable, and model agnostic." --tag launch
```

Save a file:

```bash
matriosha memory remember --file ~/Documents/agent-notes/launch-context.md --tag launch
```

Save from stdin:

```bash
cat ~/Documents/agent-notes/launch-context.md | matriosha memory remember --stdin --tag launch
```

### Use the inbox for agent and file handoff

If you set:

```bash
export MATRIOSHA_HOME=./memory
```

then the default profile inbox is:

```text
./memory/data/default/inbox
```

Create it:

```bash
mkdir -p ./memory/data/default/inbox
```

Drop files into it:

```bash
cp ~/Documents/agent-notes/launch-context.md ./memory/data/default/inbox/
```

Ingest every eligible inbox file:

```bash
matriosha memory remember
```

Matriosha encrypts each inbox file as a memory, tags it with `inbox`, preserves the filename in metadata, and moves the original file to:

```text
./memory/data/default/inbox/.processed
```

Inbox ingestion accepts regular files only. It skips hidden files, directories, symlinks, and incomplete temporary files ending in `.tmp`, `.part`, `.partial`, `.swp`, or `.crdownload`.

Maximum inbox file size is 50 MiB.

### List and search memories

List recent memories:

```bash
matriosha memory list
```

Search semantically:

```bash
matriosha memory search "launch motto"
```

Search inbox-ingested memories:

```bash
matriosha memory search "launch context" --tag inbox
```

### Recall and verify

Recall a specific memory by ID:

```bash
matriosha memory recall <memory-id>
```

Verify the vault and audit trail:

```bash
matriosha vault verify
matriosha audit verify
```

For deeper verification:

```bash
matriosha vault verify --deep
```

### JSON output for agents and scripts

Use JSON output when another tool needs to parse Matriosha responses:

```bash
matriosha --json memory search "launch context"
```

## External agent integrations

Matriosha can interoperate with external AI agent systems including OpenClaw, CrewAI, LangChain, Claude-based agents, AutoGPT, and Ollama through shared filesystem layouts, inbox ingestion workflows, and structured JSON retrieval.

See:
`docs/integrations/matriosha_agent_integrations.md`

## Agent tokens

Matriosha can issue local or managed tokens for desktop, server, and CI agents.

### Local agents

Use local agents when an AI desktop app, server process, or CI job needs controlled access to your local encrypted memory.

Local agent tokens are:

- local-only
- offline-first
- scoped with `read`, `write`, or `admin`
- optionally time-limited with `--expires`
- created and connected with the `--local` flag

Generate a local token:

```bash
matriosha token generate my-local-agent --local --scope write --expires 30d
```

The token is shown once only. Copy it immediately.

Connect a local desktop agent:

```bash
matriosha agent connect --local --name my-local-agent --kind desktop --token <token>
```

List local connected agents:

```bash
matriosha agent list --local
```

For scripts and agent setup automation, use JSON output:

```bash
matriosha --json token generate my-local-agent --local --scope write --expires 30d
matriosha --json agent connect --local --name my-local-agent --kind desktop --token <token>
matriosha --json agent list --local
```

Agent kinds are:

- `desktop`
- `server`
- `ci`

Token scopes are:

- `read`
- `write`
- `admin`

Use real tokens carefully. They are credentials for memory access.

## Managed mode, sync, and managed agents

Managed mode adds cloud-backed encrypted storage, remote operational workflows, managed agent tokens, subscription limits, and multi-device recovery.

Use managed mode when you want to:

- sync encrypted memories across devices
- connect managed desktop, server, or CI agents
- run remote operational workflows
- monitor subscription, storage, and agent limits
- recover managed vault access on a new machine

Matriosha remains local-first. Plaintext memory content is decrypted locally.

### Enable managed mode

Switch the active profile to managed mode:

```bash
matriosha mode set managed
```

Log in to the managed service:

```bash
matriosha auth login
```

Check your managed subscription and usage limits:

```bash
matriosha billing status
matriosha quota status
```

### Sync encrypted memories

Push local encrypted memories to managed storage:

```bash
matriosha vault sync
```

Continuously sync on an interval:

```bash
matriosha vault sync --watch 60
```

This syncs every 60 seconds.

### Pull encrypted memories

Pull encrypted memories from managed storage into the local vault:

```bash
matriosha vault pull
```

Use this on a new device, new profile, or after reconnecting a managed environment.

For automation, use JSON output:

```bash
matriosha --json vault sync
matriosha --json vault pull
matriosha --json billing status
matriosha --json quota status
```

### Managed search behavior

In managed mode, `memory search` is still local-first.

Matriosha first searches the local encrypted vault and local vector index. This is the fastest and richest search path, especially after pulling managed memories locally:

```bash
matriosha vault pull
matriosha memory search "launch context"
```

If no local vector candidates are found, Matriosha can ask the managed backend for up to 50 encrypted candidate memories using keyed metadata search tokens derived from the query terms and your vault data key.

The managed service does not receive your plaintext query or plaintext memory contents. It receives keyed metadata search tokens and returns encrypted candidate payloads. Matriosha then decrypts and ranks candidates locally.

This fallback is useful on a new device or profile before the full local vector index is populated.

For best managed search quality, pull first:

```bash
matriosha vault pull
matriosha memory search "launch context"
```

### Managed agent tokens

Managed agent tokens are used for cloud-backed desktop, server, and CI agents.

Generate a managed token:

```bash
matriosha token generate my-managed-agent --scope write --expires 30d
```

The token is shown once only. Copy it immediately.

Connect a managed desktop agent:

```bash
matriosha agent connect --name my-managed-agent --kind desktop --token <token>
```

List managed connected agents:

```bash
matriosha agent list
```

For scripts and agent setup automation, use JSON output:

```bash
matriosha --json token generate my-managed-agent --scope write --expires 30d
matriosha --json agent connect --name my-managed-agent --kind desktop --token <token>
matriosha --json agent list
```
## Utilities and maintenance

Use these commands to check setup health, verify vault integrity, maintain the semantic index, reduce storage use, and clean up old memories.

### Check setup status

Show a concise status summary for the active profile:

```bash
matriosha status
```

Run deeper setup diagnostics and suggested fixes:

```bash
matriosha doctor
```

Test whether a passphrase can unlock the vault:

```bash
matriosha doctor --test-passphrase "your passphrase"
```

For scripts and automation:

```bash
matriosha --json doctor
```

### Verify vault integrity

Check that local memories are intact:

```bash
matriosha vault verify
```

Run a deeper verification that decrypts each memory and verifies Merkle integrity end-to-end:

```bash
matriosha vault verify --deep
```

For automation:

```bash
matriosha --json vault verify
matriosha --json vault verify --deep
```

### Maintain the semantic index

Matriosha local mode uses a semantic index for memory recall.

The default backend is PostgreSQL with `pgvector`. Matriosha can automatically create or start a local Docker container for this database if Docker is already installed and running.

Install PostgreSQL support:

```bash
pip install "matriosha[postgres]"
```

Set a local encrypted vault root:

```bash
export MATRIOSHA_HOME=./memory
```

Create or start the local semantic index database:

```bash
matriosha memory index-start
```

Print shell exports for explicit local index configuration:

```bash
matriosha memory index-env
```

This prints:

```bash
export MATRIOSHA_LOCAL_VECTOR_BACKEND=pgvector
export MATRIOSHA_LOCAL_DATABASE_URL='postgresql://matriosha:matriosha@localhost:5432/matriosha'
export MATRIOSHA_LOCAL_DB_AUTO_START=1
```

Show local semantic index database status:

```bash
matriosha memory index-status
```

Build missing semantic vectors for saved memories:

```bash
matriosha memory index
```

Wait longer for the local index database to become ready:

```bash
matriosha memory index-start --timeout 60
```

Default local database:

```text
container: matriosha-pgvector
image: pgvector/pgvector:pg16
volume: matriosha_pgvector_data
database: postgresql://matriosha:matriosha@localhost:5432/matriosha
port: 5432
```

Notes:

- Docker is not installed by Matriosha.
- Docker must already be installed and running for automatic local database startup.
- If `MATRIOSHA_LOCAL_DATABASE_URL` is set, Matriosha uses that database.
- If `MATRIOSHA_LOCAL_DB_AUTO_START=0`, Matriosha will not create or start the default Docker container.
- The pgvector table stores embeddings and memory IDs, not plaintext memory payloads.

### Compress similar memories

Preview compression groups without writing parent memories:

```bash
matriosha memory compress --dry-run
```

Compress similar memories using the default threshold:

```bash
matriosha memory compress
```

Compress only memories with a specific tag:

```bash
matriosha memory compress --tag inbox
```

Tune the cosine similarity threshold:

```bash
matriosha memory compress --threshold 0.92
```

For automation:

```bash
matriosha --json memory compress --dry-run
matriosha --json memory compress --tag inbox
```

### Decompress a memory group

Restore memories from a compressed parent memory:

```bash
matriosha memory decompress <parent_id>
```

Keep the parent memory after restoring children:

```bash
matriosha memory decompress <parent_id> --keep-parent
```

Require a stricter child-parent similarity score:

```bash
matriosha memory decompress <parent_id> --min-similarity 0.95
```

For automation:

```bash
matriosha --json memory decompress <parent_id>
```

### Delete memories

Delete one memory by id:

```bash
matriosha memory delete <memory_id>
```

Delete memories older than a number of days:

```bash
matriosha memory delete --older-than 90
```

Delete memories semantically matching a query:

```bash
matriosha memory delete --query "temporary launch notes" --threshold 0.45 --limit 25
```

Skip the confirmation prompt:

```bash
matriosha memory delete --older-than 90 --yes
```

Exit with code 2 if a memory id does not exist:

```bash
matriosha memory delete <memory_id> --strict
```

For automation:

```bash
matriosha --json memory delete <memory_id>
matriosha --json memory delete --query "temporary launch notes" --threshold 0.45 --limit 25 --yes
```

Be careful with bulk deletion. Use search and dry-run style workflows before deleting important memory.

## Security model

Matriosha is designed around local-first, encrypted memory handling. The goal is to let agents remember useful context without turning memory storage into a plaintext database.

- **Local-first encryption** — memories are encrypted before storage or sync, and plaintext is handled locally.

- **Envelope encryption** — each vault has a random data key; the user passphrase protects that data key.

- **Authenticated encryption** — encrypted data is protected against tampering with AES-256-GCM.

- **Integrity verification** — memory payloads use SHA-256 block hashes and Merkle roots to detect corruption or modification.

- **Managed search without plaintext memory content** — managed candidate search uses keyed search tokens instead of plaintext memory text.

## Cryptographic building blocks

Matriosha uses standard cryptographic primitives rather than custom encryption algorithms.

- **Argon2id** for passphrase-based key derivation.

- **AES-256-GCM** for authenticated encryption.

- **SHA-256 and HMAC-SHA256** for integrity verification, audit chains, and keyed search tokens.
  
- **scrypt** for local token hashing and credential hardening.

- **Libsodium sealed boxes** for managed custody wrapping.

- **Ed25519 keypairs** for signature-capable workflows.

- **Secure OS randomness** for salts, nonces, data keys, and tokens.

## Requirements

- Python `>=3.11,<3.15`
- A Unix-like shell for the examples, such as Terminal on macOS, Linux shells, WSL, or Git Bash on Windows
- Optional system tools for rich file extraction, installed through `matriosha init` where supported

## Benchmarks

In the local MIRACL-style fixture run, Matriosha indexed **5,004 encrypted memories** and evaluated **300 queries**, reaching **98.67% hit@5**, **99.67% group hit@5**, and **97.98% MRR@5**. End-to-end local search latency was approximately **75 ms p50** and **81 ms p95**.

## Pricing

**Local mode** is free, offline-first, and does not require authentication. It requires the user to maintain the passphrase to avoid losing access to data.

Local mode includes:

- encrypted memory stored on your machine
- manual vault bootstrap with `matriosha vault init`
- local-only agent tokens with `--local`
- local vault and audit verification

**Managed mode** is €9/month for cloud-backed operational workflows.

Managed mode includes:

- up to **3 agents**
- up to **3 GB** of managed storage
- encrypted sync across devices and environments
- managed agent workflows to extend data access across devices
- access to future managed operational features and premium modules

Start local if you want a private offline vault. Upgrade to managed mode when you don't want to manage passphrases, managed agents, operational workflows, or access to future managed operational features and premium modules.

