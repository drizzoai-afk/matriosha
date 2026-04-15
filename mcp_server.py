import asyncio
from mcp.server.fastmcp import FastMCP
from core.brain import Brain
from core.security import Vault
from cli.utils.config import get_config

mcp = FastMCP("Matriosha")

@mcp.tool()
async def search_memory(query: str, limit: int = 5) -> str:
    """Search the user's encrypted memory vault for relevant context."""
    config = get_config()
    if not config or not config.get("vault_path"):
        return "Error: Matriosha vault not initialized. Run 'matriosha init' first."
    
    try:
        vault = Vault(config["master_key"]) # In prod, fetch from keyring
        brain = Brain(vault=vault, db_path=config.get("db_path", "./matriosha.lance"))
        results = brain.search(query, top_k=limit)
        return "\n\n".join([f"[{r['metadata'].get('timestamp')}] {r['text']}" for r in results])
    except Exception as e:
        return f"Error searching memory: {str(e)}"

@mcp.tool()
async def store_memory(content: str, importance: str = "medium") -> str:
    """Store a new piece of information in the user's encrypted memory vault."""
    config = get_config()
    if not config or not config.get("vault_path"):
        return "Error: Matriosha vault not initialized. Run 'matriosha init' first."

    try:
        vault = Vault(config["master_key"])
        brain = Brain(vault=vault, db_path=config.get("db_path", "./matriosha.lance"))
        leaf_id = brain.remember(content, importance=importance)
        return f"Memory stored successfully. Leaf ID: {leaf_id}"
    except Exception as e:
        return f"Error storing memory: {str(e)}"

if __name__ == "__main__":
    mcp.run(transport="stdio")
