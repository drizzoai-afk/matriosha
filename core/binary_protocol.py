"""
Matriosha Binary Protocol — P2: Memory Block Header

Implements a 128-bit (16-byte) binary header for memory blocks with
bit-packed metadata for token-efficient recall without decryption.

Header Structure:
┌──────────┬─────────────┬──────────────┬──────────────────┐
│ Version  │ Meta Byte   │ Timestamp    │ Leaf ID Hash     │
│ 8 bits   │ 8 bits      │ 32 bits      │ 80 bits          │
│ Byte 0   │ Byte 1      │ Bytes 2-5    │ Bytes 6-15       │
└──────────┴─────────────┴──────────────┴──────────────────┘

Meta Byte Layout (Byte 1):
┌──────────────┬──────────────┬──────────┐
│ Logic State  │ Importance   │ Reserved │
│ Bits 7-6     │ Bits 5-4     │ Bits 3-0 │
└──────────────┴──────────────┴──────────┘

Logic States:
  00 (0) = False
  01 (1) = True
  10 (2) = Uncertain

Importance Levels:
  00 (0) = Low
  01 (1) = Medium
  10 (2) = High
  11 (3) = Critical

Forward Compatibility:
  - Version field allows parsers to handle schema evolution
  - Reserved bits in meta byte reserved for future extensions
  - Unknown versions should trigger graceful degradation, not crash
"""

import struct
import time
from typing import Dict, Optional

# Constants
HEADER_SIZE = 16  # 128 bits = 16 bytes
VERSION = 1

# Logic states (2 bits)
LOGIC_FALSE = 0
LOGIC_TRUE = 1
LOGIC_UNCERTAIN = 2

# Importance levels (2 bits)
IMPORTANCE_LOW = 0
IMPORTANCE_MEDIUM = 1
IMPORTANCE_HIGH = 2
IMPORTANCE_CRITICAL = 3

# Bit masks
LOGIC_MASK = 0b11  # 2 bits
IMPORTANCE_MASK = 0b11  # 2 bits
RESERVED_MASK = 0b1111  # 4 bits

# Struct format: big-endian
# B = unsigned char (1 byte), I = unsigned int (4 bytes), 10s = 10 bytes
HEADER_FORMAT = ">B B I 10s"


def pack_header(
    version: int = VERSION,
    logic_state: int = LOGIC_UNCERTAIN,
    importance: int = IMPORTANCE_MEDIUM,
    timestamp: Optional[int] = None,
    leaf_id_hash: bytes = b"\x00" * 10,
) -> bytes:
    """
    Pack memory block metadata into a 16-byte binary header.

    Args:
        version: Protocol version (default: 1).
        logic_state: Ternary logic state (0=False, 1=True, 2=Uncertain).
        importance: Importance level (0=Low, 1=Medium, 2=High, 3=Critical).
        timestamp: Unix epoch timestamp (default: current time).
        leaf_id_hash: 10-byte truncated SHA-256 hash of encrypted content.

    Returns:
        16-byte binary header.

    Raises:
        ValueError: If any parameter is out of valid range.

    Example:
        >>> header = pack_header(logic_state=2, importance=3)
        >>> len(header)
        16
    """
    # Validate inputs
    if not (0 <= logic_state <= 2):
        raise ValueError(f"logic_state must be 0-2, got {logic_state}")
    if not (0 <= importance <= 3):
        raise ValueError(f"importance must be 0-3, got {importance}")
    if not (0 <= version <= 255):
        raise ValueError(f"version must fit in 8 bits (0-255), got {version}")
    if len(leaf_id_hash) != 10:
        raise ValueError(f"leaf_id_hash must be 10 bytes, got {len(leaf_id_hash)}")

    # Pack logic_state and importance into meta byte
    # Bits 7-6: logic_state, Bits 5-4: importance, Bits 3-0: reserved (0)
    meta_byte = (logic_state << 6) | (importance << 4)

    # Use current timestamp if not provided
    if timestamp is None:
        timestamp = int(time.time())

    # Pack into binary format (big-endian)
    header = struct.pack(HEADER_FORMAT, version, meta_byte, timestamp, leaf_id_hash)

    assert len(header) == HEADER_SIZE, f"Header must be {HEADER_SIZE} bytes"

    return header


def unpack_header(header_bytes: bytes) -> Dict:
    """
    Unpack a 16-byte binary header into its component fields.

    Args:
        header_bytes: 16-byte binary header from pack_header().

    Returns:
        Dictionary with decoded fields:
        - version: int
        - logic_state: int (0=False, 1=True, 2=Uncertain)
        - importance: int (0=Low, 1=Medium, 2=High, 3=Critical)
        - timestamp: int (Unix epoch)
        - leaf_id_hash: bytes (10 bytes)

    Raises:
        ValueError: If header is not exactly 16 bytes.

    Example:
        >>> header = pack_header(logic_state=2, importance=3)
        >>> data = unpack_header(header)
        >>> data['logic_state']
        2
        >>> data['importance']
        3
    """
    if len(header_bytes) != HEADER_SIZE:
        raise ValueError(f"Header must be {HEADER_SIZE} bytes, got {len(header_bytes)}")

    version, meta_byte, timestamp, leaf_id_hash = struct.unpack(HEADER_FORMAT, header_bytes)

    # Extract logic_state from bits 7-6
    logic_state = (meta_byte >> 6) & LOGIC_MASK

    # Extract importance from bits 5-4
    importance = (meta_byte >> 4) & IMPORTANCE_MASK

    return {
        "version": version,
        "logic_state": logic_state,
        "importance": importance,
        "timestamp": timestamp,
        "leaf_id_hash": leaf_id_hash,
    }


def validate_header(header_bytes: bytes, max_supported_version: int = VERSION) -> bool:
    """
    Validate a binary header for correctness and compatibility.

    Checks:
    - Header is exactly 16 bytes
    - Version is supported (<= max_supported_version)
    - Logic state is valid (0-2)
    - Importance is valid (0-3)

    Args:
        header_bytes: 16-byte binary header.
        max_supported_version: Maximum protocol version this parser supports.

    Returns:
        True if header is valid and compatible.

    Note:
        This function does NOT decrypt or verify the associated memory block.
        It only validates the header structure itself.
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        if len(header_bytes) != HEADER_SIZE:
            return False

        data = unpack_header(header_bytes)

        # Check version compatibility
        if data["version"] > max_supported_version:
            logger.warning(f"Future protocol version {data['version']} > supported {max_supported_version}")
            return False

        if data["version"] < 1:
            return False  # Invalid version

        # Check logic state range
        if data["logic_state"] not in (LOGIC_FALSE, LOGIC_TRUE, LOGIC_UNCERTAIN):
            return False

        # Check importance range
        if not (IMPORTANCE_LOW <= data["importance"] <= IMPORTANCE_CRITICAL):
            return False

        return True

    except (struct.error, ValueError):
        return False


def get_logic_label(logic_state: int) -> str:
    """Convert numeric logic state to human-readable label."""
    labels = {
        LOGIC_FALSE: "False",
        LOGIC_TRUE: "True",
        LOGIC_UNCERTAIN: "Uncertain",
    }
    return labels.get(logic_state, f"Unknown({logic_state})")


def get_importance_label(importance: int) -> str:
    """Convert numeric importance level to human-readable label."""
    labels = {
        IMPORTANCE_LOW: "Low",
        IMPORTANCE_MEDIUM: "Medium",
        IMPORTANCE_HIGH: "High",
        IMPORTANCE_CRITICAL: "Critical",
    }
    return labels.get(importance, f"Unknown({importance})")


def header_to_dict_for_display(header_bytes: bytes) -> Dict:
    """
    Unpack header and return human-readable dictionary with labels.

    Useful for debugging and dashboard display.

    Args:
        header_bytes: 16-byte binary header.

    Returns:
        Dictionary with decoded fields and human-readable labels.
    """
    data = unpack_header(header_bytes)
    return {
        **data,
        "logic_label": get_logic_label(data["logic_state"]),
        "importance_label": get_importance_label(data["importance"]),
        "leaf_id_hex": data["leaf_id_hash"].hex(),
    }
