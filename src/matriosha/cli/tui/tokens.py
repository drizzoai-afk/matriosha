"""Design-token bridge for the Textual launcher.

`pytailwindcss` is intentionally optional and used as a lightweight token reference
workflow only (no frontend build tooling).
"""

from __future__ import annotations

try:  # pragma: no cover - optional package
    import pytailwindcss as _tailwind_reference
except ImportError:  # pragma: no cover
    _tailwind_reference = None

TOKENS = {
    "bg": "#0a0c0e",  # obsidian
    "surface": "#12161b",
    "fg": "#d6dde3",
    "muted": "#8b949e",
    "primary": "#7CFC7C",  # phosphor green
    "secondary": "#58cfd5",  # muted cyan/electric teal
    "warning": "#d2a45a",
    "danger": "#bf5a5a",
    "success": "#4ecf78",
}

TAILWIND_REFERENCE = {
    "bg": "bg-zinc-950",
    "surface": "bg-zinc-900",
    "fg": "text-zinc-200",
    "muted": "text-zinc-500",
    "primary": "text-emerald-300",
    "secondary": "text-cyan-300",
    "warning": "text-amber-400",
    "danger": "text-rose-400",
    "success": "text-green-400",
}


def token_reference_enabled() -> bool:
    return _tailwind_reference is not None
