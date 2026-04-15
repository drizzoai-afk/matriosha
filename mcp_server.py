import asyncio  # noqa: F401
from mcp.server.fastmcp import FastMCP
from core.brain import MatrioshaBrain
from cli.utils.config import load_config

mcp = FastMCP("Matriosha")


@mcp.tool()
async def search_memory(query: str, limit: int = 5) -> str:
    """Search the user's encrypted memory vault for relevant context."""
    config = load_config()
    vault_path = config.get("vault", {}).get("path")
    if not vault_path:
        return "Error: Matriosha vault not initialized. Run 'matriosha init' first."

    try:
        from pathlib import Path
        brain = MatrioshaBrain(vault_path=Path(vault_path))
        results = brain.search(query, top_k=limit)
        return "\n\n".join([f"[{r.get('timestamp')}] {r.get('preview')}" for r in results])
    except Exception as e:
        return f"Error searching memory: {str(e)}"


@mcp.tool()
async def store_memory(content: str, importance: str = "medium") -> str:
    """Store a new piece of information in the user's encrypted memory vault."""
    config = load_config()
    vault_path = config.get("vault", {}).get("path")
    if not vault_path:
        return "Error: Matriosha vault not initialized. Run 'matriosha init' first."

    try:
        from pathlib import Path
        import time
        import hashlib
        brain = MatrioshaBrain(vault_path=Path(vault_path))

        # Generate a simple leaf_id (in prod, this would come from the binary protocol)
        leaf_id = hashlib.sha256(content.encode()).hexdigest()[:16]

        importance_map = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        imp_val = importance_map.get(importance.lower(), 1)

        brain.add_to_index(
            leaf_id=leaf_id,
            content=content,
            importance=imp_val,
            logic_state=0,
            timestamp=int(time.time())
        )
        return f"Memory stored successfully. Leaf ID: {leaf_id}"
    except Exception as e:
        return f"Error storing memory: {str(e)}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
