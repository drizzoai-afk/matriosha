"""Managed token-store compatibility module.

The canonical TokenStore implementation currently lives in
matriosha.core.managed.auth. This module provides the import path expected by
CLI auth command modules without duplicating token-store logic.
"""

from __future__ import annotations

from matriosha.core.managed.auth import TokenStore, TokenStoreError

__all__ = ["TokenStore", "TokenStoreError"]
