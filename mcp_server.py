"""
Matriosha MCP Server — Model Context Protocol Integration

Exposes secure memory operations to AI coding agents (Cursor, Windsurf, Claude Code).
Uses local-first architecture with OS keyring for key management.
"""

import os
import sys
import json
import time
import tempfile
import base64
from pathlib import Path
from typing import Optional

# Ensure project root is in path for imports
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from mcp.server.fastmcp import FastMCP
from core.security import retrieve_key_vault, encrypt_data, decrypt_data, hash_for_leaf_id
from core.binary_protocol import pack_header, unpack_header, HEADER_SIZE, LOGIC_UNCERTAIN, IMPORTANCE_MEDIUM
from core.merkle import MerkleTree, hash_leaf
from core.brain import MatrioshaBrain
from cli.utils.config import load_config, DEFAULT_CONFIG_PATH

mcp = FastMCP("Matriosha")


def _get_vault_context():
    """
    Load vault configuration and decryption key.
    Raises ValueError if vault is not initialized.
    """
    config = load_config(DEFAULT_CONFIG_PATH)
    vault_path_str = config.get("vault", {}).get("path")
    
    if not vault_path_str:
        raise ValueError("Vault not initialized. Run 'matriosha init' first.")
    
    vault_path = Path(vault_path_str)
    if not vault_path.exists():
        raise ValueError(f"Vault directory not found: {vault_path}")
    
    vault_id = vault_path.name
    try:
        key = retrieve_key_vault(vault_id)
    except KeyError:
        raise ValueError(f"Encryption key not found for vault: {vault_id}. Re-run 'matriosha init'.")
    
    return vault_path, key


@mcp.tool()
async def search_memory(query: str, limit: int = 5, min_importance: int = 0) -> str:
    """
    Search the user's encrypted memory vault for relevant context.
    
    Args:
        query: Natural language search query.
        limit: Maximum number of results to return (default: 5).
        min_importance: Minimum importance filter (0=Low, 1=Medium, 2=High, 3=Critical).
    
    Returns:
        Formatted string with matching memories, or error message.
    """
    try:
        vault_path, key = _get_vault_context()
        brain = MatrioshaBrain(vault_path)
        
        # Validate inputs
        if not isinstance(limit, int) or limit < 1 or limit > 50:
            return "Error: limit must be an integer between 1 and 50."
        if not isinstance(min_importance, int) or not (0 <= min_importance <= 3):
            return "Error: min_importance must be 0-3."
        
        results = brain.search(query=query, top_k=limit, min_importance=min_importance)
        
        if not results:
            return "No memories found matching your query."
        
        memories = []
        for result in results:
            leaf_id = result["leaf_id"]
            block_file = vault_path / f"{leaf_id}.bin"
            
            if not block_file.exists():
                continue
            
            try:
                block_data = block_file.read_bytes()
                if len(block_data) < HEADER_SIZE + 28:
                    continue
                
                header = unpack_header(block_data[:HEADER_SIZE])
                remaining = block_data[HEADER_SIZE:]
                tag = remaining[-16:]
                nonce = remaining[-28:-16]
                ciphertext = remaining[:-28]
                
                plaintext = decrypt_data(
                    key,
                    base64.b64encode(ciphertext).decode(),
                    base64.b64encode(nonce).decode(),
                    base64.b64encode(tag).decode(),
                )
                
                content = json.loads(plaintext.decode("utf-8"))
                memories.append({
                    "text": content.get("text", ""),
                    "timestamp": header["timestamp"],
                    "importance": header["importance"],
                    "relevance_score": result.get("relevance_score", 0),
                })
            except Exception:
                continue
        
        if not memories:
            return "Found matches but could not decrypt any blocks."
        
        output_lines = []
        for i, mem in enumerate(memories, 1):
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(mem["timestamp"]))
            output_lines.append(f"[{ts}] (Importance: {mem['importance']}/3) {mem['text']}")
        
        return "\n\n".join(output_lines)
    
    except ValueError as e:
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error searching memory: {type(e).__name__}: {str(e)}"


@mcp.tool()
async def store_memory(content: str, importance: str = "medium", logic_state: str = "uncertain") -> str:
    """
    Store a new piece of information in the user's encrypted memory vault.
    
    Args:
        content: The memory content to store.
        importance: Importance level (low, medium, high, critical).
        logic_state: Logic state (true, false, uncertain).
    
    Returns:
        Success message with Leaf ID, or error message.
    """
    try:
        vault_path, key = _get_vault_context()
        
        # Map string params to numeric values
        importance_map = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        logic_map = {"true": 1, "false": 0, "uncertain": 2}
        
        importance_val = importance_map.get(importance.lower(), IMPORTANCE_MEDIUM)
        logic_val = logic_map.get(logic_state.lower(), LOGIC_UNCERTAIN)
        
        timestamp = int(time.time())
        memory_content = json.dumps({
            "text": content,
            "tags": [],
            "created_at": timestamp,
        }).encode("utf-8")
        
        # Encrypt
        encrypted = encrypt_data(key, memory_content)
        ciphertext_bytes = base64.b64decode(encrypted["ciphertext"])
        leaf_id_hash = hash_for_leaf_id(ciphertext_bytes)[:10]
        
        # Pack header
        header = pack_header(
            version=1,
            logic_state=logic_val,
            importance=importance_val,
            timestamp=timestamp,
            leaf_id_hash=leaf_id_hash,
        )
        
        # Assemble block
        block = header + ciphertext_bytes + base64.b64decode(encrypted["nonce"]) + base64.b64decode(encrypted["tag"])
        
        leaf_id = leaf_id_hash.hex()
        block_file = vault_path / f"{leaf_id}.bin"
        
        # Atomic write
        fd, tmp_path = tempfile.mkstemp(dir=vault_path)
        try:
            with os.fdopen(fd, 'wb') as tmp_file:
                tmp_file.write(block)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            os.replace(tmp_path, block_file)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise
        
        # Update search index
        try:
            brain = MatrioshaBrain(vault_path)
            brain.add_to_index(
                leaf_id=leaf_id,
                content=content,
                importance=importance_val,
                logic_state=logic_val,
                timestamp=timestamp,
            )
        except Exception:
            # Index update failure shouldn't block storage
            pass
        
        return f"Memory stored successfully. Leaf ID: {leaf_id}"
    
    except ValueError as e:
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error storing memory: {type(e).__name__}: {str(e)}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
