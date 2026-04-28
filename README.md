# Matriosha

Matriosha is a Python CLI for encrypted agent memory with verifiable integrity.

It supports two explicit modes:

- **Local mode**: sovereign, offline-first encrypted memory. No authentication required.
- **Managed mode**: subscription-gated sync, policy, quota, billing, token, and agent workflows.

Matriosha v2 is **CLI-only**. Web frontends, React components, browser OAuth flows, and non-core assets are outside the active implementation path.

## Requirements

- Python `>=3.11,<3.15`
- A POSIX-like shell for the examples below
- Optional system tools for rich file extraction, installed through `matriosha init` where supported

## Install for development

```bash
git clone <repo-url>
cd matriosha
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

Check the CLI:

```bash
matriosha --help
matriosha --version
```

## First run: local mode

Local mode is the default. It keeps cryptographic control on the user machine.

```bash
matriosha mode set local
matriosha vault init
matriosha memory remember "hello from local mode" --tag demo
matriosha memory search "hello"
matriosha vault verify
```

In local mode, `matriosha vault init` is the manual key bootstrap command.

## First run: managed mode

Managed mode requires authentication and a managed subscription.

```bash
matriosha mode set managed
matriosha auth login
matriosha billing status
matriosha memory remember "hello from managed mode" --tag demo
matriosha vault sync
```

Managed mode automatically provisions managed key custody after successful authentication. Managed users should not be asked to manually generate keys, copy key files, or manage crypto passphrases for normal managed workflows.

## Pricing model

Managed billing uses scalable 3-agent packs:

| Agent packs | Agents | Storage cap | Monthly price |
|---:|---:|---:|---:|
| 1 | 3 | 3 GB | €9/month |
| 2 | 6 | 6 GB | €18/month |
| 3 | 9 | 9 GB | €27/month |

Relevant commands:

```bash
matriosha billing status
matriosha billing subscribe --agent-pack-count 1
matriosha billing upgrade
matriosha billing cancel --yes
```

## Command map

Top-level command groups:

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

Common workflows:

```bash
matriosha status
matriosha doctor
matriosha quota status
matriosha memory list
matriosha memory recall <memory-id>
matriosha memory delete <memory-id> --yes
matriosha memory compress --deduplicate
matriosha token generate --local
matriosha agent list
```

Use `--json` for automation and agent integrations:

```bash
matriosha --json memory search "contract renewal"
```

JSON output is treated as a machine-readable contract. Human prompts and troubleshooting output must not corrupt JSON stdout.

## Semantic interpreter support

Matriosha can return structured semantic envelopes for recalled files. Built-in rich extraction targets common formats such as text, Markdown, JSON, CSV/TSV, PDF, images, DOCX, and XLSX. Unknown or unsupported binary formats still return safe structured fallback metadata.

Optional decoder plugins can be added through the `matriosha.decoders` entry-point group.

## Testing and quality gates

Run the main local checks:

```bash
ruff check src tests scripts
mypy src/matriosha
pytest --cov=matriosha --cov-report=term-missing --cov-fail-under=70 -m "not managed"
bandit -q -r src/matriosha
pip-audit
```

Focused test examples:

```bash
pytest tests/test_cmd_billing.py
pytest tests/test_legacy_command_cleanup.py
```

Real managed/backend integration tests require credentials and are promoted to their own workflow in `.github/workflows/integration-tests.yml`.

## Repository guide

| Path | Purpose |
|---|---|
| `src/matriosha` | CLI and core implementation |
| `tests` | Unit and integration tests |
| `.github/workflows/quality-gates.yml` | Pull request quality gates |
| `.github/workflows/integration-tests.yml` | Real backend integration workflow |
| `docs/ci/integration-tests.workflow.yml` | Portable copy of the backend integration workflow |
| `docs/adr` | Architecture Decision Records |
| `SPECIFICATION.md` | Active product and implementation specification |
| `SECURITY.md` | Security policy and reporting guidance |
| `BACKEND_SETUP.md` | Backend setup notes |
| `deployment_guide.md` | Deployment guidance |

## Documentation

Start here:

- `SPECIFICATION.md` for normative product behavior.
- `DESIGN.md` for design notes.
- `SECURITY.md` for security expectations.
- `docs/adr/README.md` for durable architecture/security decisions.
- `docs/DEPENDENCIES.md` for optional runtime dependency details, when present.

## Development notes

- Keep local and managed mode behavior visibly distinct.
- Keep JSON stdout clean for automation.
- Do not reintroduce old top-level legacy commands such as `matriosha remember`, `matriosha recall`, `matriosha verify`, or `matriosha sync`.
- Prefer grouped commands such as `matriosha memory remember`, `matriosha memory recall`, `matriosha vault verify`, and `matriosha vault sync`.


## Python 3.14+ Installation

For Python 3.14.4 and newer, some optional vector-stack dependencies may not have pre-built wheels yet on all platforms.

**Recommended installation (base runtime):**

```bash
pip install "git+https://github.com/drizzoai-afk/matriosha_legacy.git@launch-readiness-e2e"
```

If you need optional LanceDB/PyArrow features, install with the `vector` extra and see [INSTALL_PYTHON_3.14.md](INSTALL_PYTHON_3.14.md) for alternatives/workarounds.


## SSL Certificate Handling

Matriosha automatically bundles SSL certificates via `certifi`. No manual certificate installation is required, including on macOS Python 3.14+.

If you still encounter SSL errors:

```bash
pip install --upgrade certifi
```
