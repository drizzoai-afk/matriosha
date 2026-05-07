## Filesystem agent integrations

Matriosha is designed to work alongside local AI agents and agent frameworks using shared filesystem-based memory layouts.

Many modern AI agent systems already support configurable storage roots, local JSON persistence, workspace relocation, or symbolic-link-based memory organization. Matriosha can coexist with these systems as an encrypted local memory layer and shared operational storage root.

This interoperability model keeps memory portable, auditable, model-agnostic, and independent from any single provider or framework.

### Shared local memory root

A common pattern is to place multiple agent systems under the same local operational root:

```bash
export MATRIOSHA_HOME="$HOME/.matriosha"
```

Example layout:

```text
$MATRIOSHA_HOME/
├── data/
│   └── default/
│       ├── inbox/
│       ├── memories/
│       └── audit/
├── integrations/
│   ├── openclaw/
│   ├── crewai/
│   ├── claude/
│   ├── autogpt/
│   ├── langchain/
│   └── ollama/
└── config/
```

### Inbox interoperability

External agents can export context files into the Matriosha inbox:

```text
$MATRIOSHA_HOME/data/default/inbox
```

Example:

```bash
cp agent-output.md "$MATRIOSHA_HOME/data/default/inbox/"
```

Then explicitly ingest and encrypt all eligible inbox files:

```bash
matriosha memory remember
```

Matriosha:

- encrypts each memory locally
- stores audit metadata
- indexes semantic content
- tags inbox-ingested memories with `inbox`
- moves processed files into:

```text
$MATRIOSHA_HOME/data/default/inbox/.processed
```

### JSON output for agents

Use JSON mode for agent interoperability and automation:

```bash
matriosha --json memory search "deployment context"
```

This allows external agents and orchestration frameworks to consume structured memory results safely.

### OpenClaw integration

OpenClaw workspaces can be redirected into a shared Matriosha-managed operational root:

```bash
export OPENCLAW_WORKSPACE="$MATRIOSHA_HOME/integrations/openclaw"
```

OpenClaw-generated notes, plans, or artifacts can then be copied or exported into the Matriosha inbox for encrypted ingestion.

### CrewAI integration

CrewAI storage can be relocated with:

```bash
export CREWAI_STORAGE_DIR="$MATRIOSHA_HOME/integrations/crewai"
```

Crew outputs can then be periodically exported into the Matriosha inbox:

```bash
cp crew-results/*.md "$MATRIOSHA_HOME/data/default/inbox/"
matriosha memory remember
```

### Claude Code integration

Claude Code configuration and workspace roots can coexist under a shared local operational directory:

```bash
export CLAUDE_CONFIG_DIR="$MATRIOSHA_HOME/integrations/claude"
```

Generated session summaries or memory exports can be explicitly ingested into Matriosha.

### Claude Desktop MCP memory integration

Filesystem-based MCP memory files can be linked into the Matriosha operational root using symbolic links:

```bash
ln -s "$MATRIOSHA_HOME/integrations/claude/memory.json" ~/mcp-memory/memory.json
```

This allows external MCP tooling and Matriosha workflows to coexist within the same filesystem-oriented memory architecture.

### AutoGPT integration

AutoGPT local memory and workspace files can be redirected into a shared directory:

```bash
export AUTOGPT_WORKSPACE="$MATRIOSHA_HOME/integrations/autogpt"
```

Structured outputs can then be encrypted through explicit inbox ingestion workflows.

### LangChain and LangGraph integration

LangChain and LangGraph applications commonly support pluggable persistence layers and local storage backends.

Matriosha can operate alongside these systems as:

- encrypted long-term memory storage
- local audit storage
- semantic archival memory
- filesystem-based retrieval infrastructure

Applications can export summaries, checkpoints, or memory snapshots into the Matriosha inbox for explicit encrypted ingestion.

### Ollama integration

Ollama models remain local-first and work naturally with Matriosha local memory workflows.

A common architecture is:

```text
Ollama model
    ↓
Agent framework
    ↓
Matriosha encrypted memory
```

This separates model execution from persistent encrypted memory handling.

### Design philosophy

Matriosha intentionally separates:

- model execution
- orchestration
- memory persistence
- encryption
- audit verification

This keeps AI memory portable, inspectable, local-first, and independent from proprietary orchestration systems.
