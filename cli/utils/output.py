"""
Matriosha CLI Utils — Rich Output Formatter

Handles beautiful human-readable and JSON output for CLI commands.
Uses Rich library for colors, panels, tables, and progress indicators.
Ensures agent-friendly structured output with --json flag.
"""

import json
from typing import Any, Dict, List, Optional
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


def format_human(text: str) -> None:
    """Print human-readable text to stdout with Rich formatting."""
    console.print(text)


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
    Format and print memory recall results with Rich UI.

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
            console.print("\n[yellow]⚠ No memories found.[/yellow]\n")
            return

        # Header
        console.print(f"\n[bold cyan]Found {len(memories)} memories:[/bold cyan]\n")

        for i, mem in enumerate(memories, 1):
            importance_labels = {0: "Low", 1: "Medium", 2: "High", 3: "Critical"}
            logic_labels = {0: "False", 1: "True", 2: "Uncertain"}

            importance_colors = {0: "blue", 1: "cyan", 2: "yellow", 3: "red bold"}
            logic_colors = {0: "red", 1: "green", 2: "yellow"}

            importance_style = importance_colors.get(mem['importance'], "white")
            logic_style = logic_colors.get(mem['logic_state'], "white")

            verified_icon = "[green]✓[/green]" if mem.get('merkle_verified') else "[red]✗[/red]"

            # Create memory card
            card = Table.grid(padding=1)
            card.add_column(style="bold white", justify="right")
            card.add_column(style="white")

            card.add_row("Memory #:", f"[accent]{i}[/accent]")
            card.add_row("Importance:", f"[{importance_style}]{importance_labels.get(mem['importance'], '?')}[/{importance_style}]")
            card.add_row("Logic State:", f"[{logic_style}]{logic_labels.get(mem['logic_state'], '?')}[/{logic_style}]")
            card.add_row("Integrity:", verified_icon)

            if 'relevance_score' in mem:
                card.add_row("Relevance:", f"{mem['relevance_score']:.2%}")

            if 'timestamp' in mem:
                timestamp = datetime.fromtimestamp(mem['timestamp']).strftime('%Y-%m-%d %H:%M')
                card.add_row("Timestamp:", timestamp)

            console.print(Panel(
                card,
                title=f"[bold]Memory {i}[/bold]",
                border_style="cyan",
            ))

            # Content preview
            content_preview = mem['content'][:300]
            if len(mem['content']) > 300:
                content_preview += "..."

            console.print(f"  [dim]{content_preview}[/dim]\n")

        # Footer stats
        if query_time_ms is not None:
            status_color = "green" if integrity_status == "valid" else "red"
            console.print(f"[dim]Query time: {query_time_ms:.0f}ms | Integrity: [{status_color}]{integrity_status}[/{status_color}][/dim]\n")


def show_progress(description: str, total: Optional[int] = None):
    """
    Show a Rich progress spinner for long operations.

    Usage:
        with show_progress("Processing...") as progress:
            task = progress.add_task("Working...", total=100)
            # ... do work ...
    """
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    )
