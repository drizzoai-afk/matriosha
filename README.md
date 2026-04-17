# Matriosha ⚡

**The First Verifiable AI Memory.**  
*Your data is encrypted, indexed, and mathematically proven to be untampered. Local-first, tiered-storage, and ready for production.*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

---

## 🪰 Why Matriosha?

Most AI memory systems are black boxes. They summarize your data, lose context, and offer no proof of integrity. **Matriosha** treats your memories like a vault: every block is encrypted (AES-256), indexed for semantic search (LanceDB), and verified by a Merkle Tree.

### The "Anti-Lock-in" Promise
Tired of vendor lock-in and rising API costs? Matriosha is **portable**, **sovereign**, and **truly unlimited**.
*   **Zero-Knowledge:** We can't read your data even if we wanted to.
*   **Knowledge Graph:** Native entity extraction and temporal fact tracking.
*   **Smart Compression:** Reduce token usage by 80% with local LLM fusion.
*   **Tiered Storage:** Hot (Supabase) + Cold (R2) for infinite scale at ~$0.02/GB.
*   **Verifiable Integrity:** Know exactly when and if a memory has been altered.

---

## 🚀 Quick Start for Vibe Coders

Get Matriosha running in 30 seconds. No cloud accounts needed.

```bash
pip install matriosha
matriosha init --local
matriosha remember "The project specs are in the /docs folder"
matriosha recall "Where are the specs?"
```

### 🔌 Connect to Cursor / Windsurf
Make your AI assistant remember everything automatically via MCP:

```json
// ~/.cursor/mcp.json
{
  "mcpServers": {
    "matriosha": {
      "command": "python",
      "args": ["-m", "matriosha.mcp_server"]
    }
  }
}
```

---

## 📊 Performance & Benchmarks

We believe in honest numbers. Here is how Matriosha performs on standard datasets:

| Metric | Score | Notes |
| :--- | :---: | :--- |
| **Recall R@5 (Raw)** | **95%+** | LanceDB HNSW indexing. |
| **Latency (Hot)** | **<80ms** | Local-first architecture. |
| **Integrity** | **100%** | Merkle Tree verification. |
| **Storage Cost** | **~$0.02/GB** | Using Cloudflare R2 for archival. |

*Full benchmark scripts and raw results are available in `benchmarks/`.*

---

## 🛠️ Architecture

*   **Core:** Python 3.11+ with AES-256-GCM encryption.
*   **Brain:** LanceDB for high-performance semantic search.
*   **Adapter:** Atomic writes and Hot/Cold storage logic.
*   **Dashboard:** Next.js 15 + shadcn/ui for visual management.

---

## 🤝 Contributing

PRs welcome! See [CONTRIBUTING.md](CONTRIBUTING.md).

## 📜 License

MIT — see [LICENSE](LICENSE).
