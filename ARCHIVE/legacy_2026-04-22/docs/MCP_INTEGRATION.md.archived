# Matriosha MCP Integration

Matriosha exposes its core functionality via the **Model Context Protocol (MCP)**, allowing AI coding agents like Cursor, Windsurf, and Claude Code to access your encrypted memory vault directly.

## 1. Configuration

Add the following to your MCP configuration file:

### For Cursor / Windsurf (`~/.cursor/mcp.json` or `.windsurfrules`)
```json
{
  "mcpServers": {
    "matriosha": {
      "command": "python",
      "args": ["/path/to/matriosha/mcp_server.py"]
    }
  }
}
```

### For Claude Code
```bash
claude mcp add matriosha python /path/to/matriosha/mcp_server.py
```

## 2. Available Tools

Once connected, your AI agent can use these tools:

*   `search_memory(query: str)`: Retrieves relevant context from your vault.
*   `store_memory(content: str)`: Saves new information securely with AES-256 encryption.

## 3. Why use MCP?
*   **Context Awareness:** Your AI assistant remembers project specs, preferences, and past decisions without you re-pasting them.
*   **Zero-Friction:** No need to switch to the CLI; just ask your AI "What did we decide about the database schema?"
*   **Secure:** All data remains encrypted and local to your machine.
