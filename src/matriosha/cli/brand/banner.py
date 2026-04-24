"""ASCII banner primitive for Matriosha CLI branding."""

from rich.console import Console

BANNER = """            1010101010101
         1010┌─────────┐0101
       1010  │101010101│ 0101
      1010 ┌─┴─────────┴─┐ 0101
     1010  │ 01010101010 │ 0101
     1010  │ ┌─────────┐ │ 0101
     1010  │ │101010101│ │ 0101
     1010  │ └─────────┘ │ 0101
      1010 └─────────────┘ 0101
       1010    1010101    0101
          10101010101010101
              MATRIOSHA"""


def print_banner(c: Console) -> None:
    """Render the Matriosha brand banner with primary style."""

    c.print(BANNER, style="primary")
