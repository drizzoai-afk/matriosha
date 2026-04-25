"""Memory command package with isolated subcommand modules."""

from __future__ import annotations

import typer

from .common import *

app = typer.Typer(help="Save, find, and manage encrypted memories.", no_args_is_help=True)

from .remember import register as register_remember

register_remember(app)


from .recall import register as register_recall
from .search import register as register_search
from .list import register as register_list
from .delete import register as register_delete
from .compress import register as register_compress
from .decompress import register as register_decompress

register_recall(app)
register_search(app)
register_list(app)
register_delete(app)
register_compress(app)
register_decompress(app)
