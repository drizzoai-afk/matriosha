"""Memory command package with isolated subcommand modules."""

from __future__ import annotations

import typer

from .common import decode_envelope as decode_envelope
from .common import threading as threading
from .common import ManagedBackupStore as ManagedBackupStore
from .common import ManagedClient as ManagedClient
from .common import SyncEngine as SyncEngine
from .common import _resolve_passphrase as _resolve_passphrase
from .compress import register as register_compress
from .decompress import register as register_decompress
from .delete import register as register_delete
from .index import register as register_index
from .index_db import register as register_index_db
from .list import register as register_list
from .recall import register as register_recall
from .remember import register as register_remember
from .search import register as register_search

app = typer.Typer(help="Save, find, and manage encrypted memories.", no_args_is_help=True)

register_remember(app)
register_recall(app)
register_search(app)
register_index(app)
register_index_db(app)
register_list(app)
register_delete(app)
register_compress(app)
register_decompress(app)
