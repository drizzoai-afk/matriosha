# Command: Generate P1-P3 Core Files

**Purpose:** Generate the cryptographic foundation files for Matriosha (security.py, binary_protocol.py, merkle.py)

**Model:** Qwen 3.6 Plus (via Abacus RouteLLM)  
**Context Files:** SPEC.md, .agent/CONTEXT.md, .agent/rules/security.md, .agent/rules/stack.md

---

## Execution Steps

### Step 1: Generate security.py (P1)

```bash
abacus generate core/security.py \
  --model qwen3.6-plus \
  --context "SPEC.md,.agent/CONTEXT.md,.agent/rules/security.md" \
  --prompt "
    Implement AES-256-GCM encryption and Argon2id KDF for Matriosha.
    
    Requirements:
    - Function: derive_key(password: str, salt: bytes) -> bytes using Argon2id with time_cost=3, memory_cost=64MB, parallelism=4
    - Function: encrypt_data(key: bytes, plaintext: bytes) -> dict with {ciphertext: base64, nonce: base64, tag: base64}
    - Function: decrypt_data(key: bytes, ciphertext: base64, nonce: base64, tag: base64) -> bytes
    - Integration with Python keyring for session key storage (never write keys to disk)
    - Salt generation: 16-byte random, unique per vault
    - All functions type-hinted with docstrings explaining cryptographic decisions
    - Include inline comments for every security-critical line
    
    Follow OWASP A02 guidelines strictly. Use cryptography.hazmat.primitives.ciphers.aead.AESGCM.
  "
```

### Step 2: Generate binary_protocol.py (P2)

```bash
abacus generate core/binary_protocol.py \
  --model qwen3.6-plus \
  --context "SPEC.md,.agent/CONTEXT.md" \
  --prompt "
    Implement 128-bit binary header packer/unpacker for Matriosha memory blocks.
    
    Header structure (16 bytes):
    - Byte 0: Version (8 bits)
    - Byte 1: Meta byte (packed):
      - Bits 7-6: Logic State (00=False, 01=True, 10=Uncertain)
      - Bits 5-4: Importance (00=Low, 01=Medium, 10=High, 11=Critical)
      - Bits 3-0: Reserved
    - Bytes 2-5: Timestamp (32-bit Unix epoch)
    - Bytes 6-15: Leaf ID Hash (80-bit truncated SHA-256)
    
    Functions:
    - pack_header(version: int, logic_state: int, importance: int, timestamp: int, leaf_id_hash: bytes) -> bytes (16 bytes)
    - unpack_header(header_bytes: bytes) -> dict with {version, logic_state, importance, timestamp, leaf_id_hash}
    - validate_header(header_bytes: bytes) -> bool (check version compatibility, logic/importance ranges)
    
    Use struct module with big-endian format. Include forward-compatibility checks.
    Type-hinted with comprehensive docstrings.
  "
```

### Step 3: Generate merkle.py (P3)

```bash
abacus generate core/merkle.py \
  --model qwen3.6-plus \
  --context "SPEC.md,.agent/CONTEXT.md" \
  --prompt "
    Implement Merkle Tree for Matriosha integrity verification.
    
    Classes:
    - MerkleTree: 
      - __init__(leaf_hashes: List[bytes])
      - build_tree() -> bytes (returns Merkle Root)
      - get_proof(leaf_index: int) -> List[dict] (returns sibling hashes + positions for Proof-of-Inclusion)
      - verify_proof(leaf_hash: bytes, proof: List[dict], root: bytes) -> bool
    
    Functions:
    - hash_leaf(data: bytes) -> bytes (SHA-256)
    - hash_nodes(left: bytes, right: bytes) -> bytes (SHA-256 of concatenation)
    
    Requirements:
    - Handle odd number of leaves (duplicate last leaf)
    - Proof format: [{\"hash\": base64, \"position\": \"left\"|\"right\"}, ...]
    - All functions type-hinted with docstrings
    - Include unit test examples in docstrings
    
    Follow OWASP A08 guidelines for integrity. Use hashlib.sha256.
  "
```

### Step 4: Security Audit with Gemma 4

```bash
abacus audit core/ \
  --model gemma-4-31b \
  --focus "owasp-top10,cryptographic-failures,integrity" \
  --rules ".agent/rules/security.md" \
  --output audit-report.md
```

### Step 5: Review Audit Report

Read `audit-report.md` and fix any CRITICAL or HIGH severity issues before proceeding to P4.

---

## Expected Output Files

```
core/
├── __init__.py
├── security.py         # ~150 lines
├── binary_protocol.py  # ~100 lines
└── merkle.py           # ~200 lines
```

---

## Validation Checklist

After generation, verify:
- [ ] All files have type hints on every function
- [ ] Docstrings explain cryptographic decisions
- [ ] No hardcoded secrets or keys
- [ ] AES-256-GCM used (not Fernet/CBC)
- [ ] Argon2id parameters match spec (time_cost=3, memory_cost=64MB, parallelism=4)
- [ ] Binary header is exactly 16 bytes
- [ ] Merkle proof verification works with sample data
- [ ] `pip-audit` scan clean
- [ ] Gemma 4 audit report has no CRITICAL issues

---

## Next Command

After P1-P3 validation:
```bash
abacus run p4-brain --context SPEC.md
```
