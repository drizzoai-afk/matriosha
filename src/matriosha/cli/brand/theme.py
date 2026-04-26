"""Shared Rich theme for Matriosha CLI visual identity."""

from rich.console import Console
from rich.theme import Theme

# Palette aligned with the Daytona-inspired CLI visual standards.
# Primary/accent/success/warning/danger map to semantic command output styles.
MATRIOSHA_THEME = Theme(
    {
        "primary": "#E6EDF3",
        "accent": "#2F81F7",
        "success": "#3FB950",
        "warning": "#D29922",
        "danger": "#F85149",
        "muted": "dim",
        "integrity": "#A371F7",
    }
)


def console() -> Console:
    """Return a Rich console instance configured with the Matriosha theme."""

    return Console(theme=MATRIOSHA_THEME, highlight=False)
