"""
Matriosha CLI Utils — Output Formatter

Handles human-readable and JSON output for CLI commands.
Ensures agent-friendly structured output with --json flag.
"""

import json
import sys
from typing import Any, Dict, List, Optional
from datetime import datetime


def format_human(text: str) -> None:
    """Print human-readable text to stdout."""
    print(text)


def format_json(data: Any, indent: int = 2) -> None:
    """Print JSON-formatted data to stdout."""
    print(json.dumps(data, indent=indent, default=str))


def format_memory_list(
    memories: List[Dict],
    output_format: str = "human",
    query_time_ms: Optional[float] = None,
    integrity_status: str = "valid",
) -> None:
    """
    Format and print memory recall results.

    Args:
        memories: List of memory dicts with keys:
            - leaf_id: str
            - importance: int (0-3)
            - logic_state: int (0-2)
            - timestamp: int
            - content: str
            - merkle_verified: bool
            - relevance_score: float
        output_format: "human" or "json"
        query_time_ms: Optional query timing info
        integrity_status: "valid" | "invalid" | "unknown"
    """
    if output_format == "json":
        result = {
            "memories": memories,
            "integrity": integrity_status,
            "count": len(memories),
        }
        if query_time_ms is not None:
            result["query_time_ms"] = round(query_time_ms, 2)
        format_json(result)
    else:
        if not memories:
            print("No memories found.")
            return

        print(f"\nFound {len(memories)} memories:\n")
        for i, mem in enumerate(memories, 1):
            importance_labels = {0: "Low", 1: "Medium", 2: "High", 3: "Critical"}
            logic_labels = {0: "False", 1: "True", 2: "Uncertain"}

            print(f"[{i}] Importance: {importance_labels.get(mem['importance'], '?')} | "
                  f"Logic: {logic_labels.get(mem['logic_state'], '?')} | "
                  f"Verified: {'✓' if mem.get('merkle_verified') else '✗'}")
            print(f"    {mem['content'][:200]}")
            if len(mem['content']) > 200:
                print("    ...")
            print()

        if query_time_ms is not None:
            print(f"Query time: {query_time_ms:.0f}ms | Integrity: {integrity_status}")")
