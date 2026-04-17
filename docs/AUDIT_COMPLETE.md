# Matriosha — Audit Completo

**Data:** 2026-04-16  
**Auditor:** Nero ⚡ (Qwen 3.6 Plus)  
**Scope:** core/, cli/, mcp_server.py, GCP secrets integration

---

## 🔴 CRITICAL — Bloccanti prima del deploy

### 1. GCP Secrets: Nessuna autenticazione configurata sul server

**Problema:** `check_secrets()` restituisce `False` per tutti gli 11 secrets. Il service account GCP non è autenticato sul server Linux.

**Root cause:** Manca `GOOGLE_APPLICATION_CREDENTIALS` env var che punta al file JSON del service account. I secrets sono su GCP ma il codice Python non può leggerli senza credenziali.

**Fix:**
```bash
# Copia gcp-sa-key.json dal Mac al server
scp ~/Downloads/gcp-sa-key.json ubuntu@SERVER:/home/ubuntu/.matriosha/gcp-sa-key.json
chmod 600 /home/ubuntu/.matriosha/gcp-sa-key.json

# Imposta env var permanente
echo 'export GOOGLE_APPLICATION_CREDENTIALS=/home/ubuntu/.matriosha/gcp-sa-key.json' >> ~/.bashrc
echo 'export GCP_PROJECT=matriosha' >> ~/.bashrc
source ~/.bashrc
```

**Impatto:** Senza questo fix, Matriosha non può connettersi a Supabase, Clerk, Stripe, R2. Tutto crasha.

---

### 2. SQL Injection in `brain.py` — `remove_from_index()`

**File:** `core/brain.py`, riga ~118

```python
self.table.delete(f"leaf_id = '{leaf_id}'")
```

**Problema:** Concatenazione diretta di stringhe nella query SQL. Anche se c'è una validazione hex, è un pattern pericoloso e la validazione è bypassabile se il tipo cambia.

**Fix:** Usare parameterized queries se LanceDB le supporta, oppure validazione più stretta:
```python
import re
if not re.match(r'^[a-f0-9]{20}$', leaf_id):  # 10 bytes = 20 char hex
    raise ValueError(f"Invalid leaf_id format: {leaf_id}")
self.table.delete(f"leaf_id = '{leaf_id}'")
```

---

### 3. Race condition nel Merkle Tree durante sync concorrente

**File:** `core/merkle.py`

**Problema:** Se due processi scrivono blocchi contemporaneamente e entrambi ricostruiscono l'albero Merkle, il root hash sarà inconsistente. Non c'è locking sul rebuild dell'albero.

**Fix:** Usare `portalocker` anche per operazioni Merkle:
```python
import portalocker
lock_file = vault_path / ".merkle.lock"
with portalocker.Lock(lock_file, timeout=10):
    tree = MerkleTree(leaf_hashes)
    root = tree.build_tree()
```

---

## 🟠 HIGH — Bug funzionali

### 4. `recall.py` non verifica il Merkle Proof-of-Inclusion

**File:** `cli/commands/recall.py`, riga ~78

```python
"merkle_verified": True,  # TODO: implement actual Merkle verification
```

**Problema:** Il flag è hardcoded a `True`. La spec dice esplicitamente "Every fetch from Supabase/R2 MUST verify Proof-of-Inclusion before decrypt". Questo è un violation della security constraint #9 in CONTEXT.md.

**Fix:** Implementare verifica reale:
```python
from core.merkle import MerkleTree
# Carica Merkle root da config/metadata
proof = tree.get_proof(leaf_index)
is_valid = MerkleTree.verify_proof(leaf_hash, proof, expected_root)
```

---

### 5. `remember.py` calcola leaf_id_hash sul ciphertext invece che sul blocco completo

**File:** `cli/commands/remember.py`, riga ~67

```python
ciphertext_bytes = base64.b64decode(encrypted["ciphertext"])
leaf_id_hash = hash_for_leaf_id(ciphertext_bytes)[:10]
```

**Problema:** La spec dice "SHA-256 of encrypted binary block". Il blocco completo include header + ciphertext + nonce + tag. Calcolare l'hash solo sul ciphertext crea inconsistenza con la verifica Merkle.

**Fix:** Hash sull'intero blocco dopo la costruzione:
```python
block = header + ciphertext_bytes + nonce_bytes + tag_bytes
leaf_id_hash = hash_for_leaf_id(block)[:10]
```

Ma questo crea un chicken-and-egg problem: l'header contiene il leaf_id_hash, ma il leaf_id_hash dipende dall'header. Soluzione: hash solo su ciphertext+nonce+tag (escludi header), documentalo chiaramente.

---

### 6. `brain.py` ricrea l'indice HNSW ad ogni `add_to_index()`

**File:** `core/brain.py`, riga ~72

```python
try:
    self.table.create_index(...)
except Exception:
    pass  # Index might already exist
```

**Problema:** Chiamare `create_index()` ad ogni insert è costoso e silenziosamente fallisce se l'indice esiste già. L'eccezione generica nasconde errori reali.

**Fix:** Creare l'indice solo alla prima inizializzazione:
```python
def _init_table(self):
    # ... crea/apri tabella
    if TABLE_NAME not in self.db.table_names():
        table = self.db.create_table(TABLE_NAME, schema=schema)
        table.create_index(vector_column_name="embedding", ...)
        return table
    return self.db.open_table(TABLE_NAME)
```

---

### 7. Nessuna gestione errori per keyring su headless Linux

**File:** `core/security.py`, `retrieve_key_vault()`

**Problema:** Su server Linux senza desktop environment (SSH, Docker, VPS), `keyring` può fallire con `keyring.errors.KeyringLocked` o `KeyringError` se non c'è Secret Service disponibile. Il CLI crasha senza fallback.

**Fix:** Fallback a file criptato se keyring non disponibile:
```python
try:
    key_b64 = keyring.get_password(...)
except keyring.errors.KeyringError:
    # Fallback: leggi da file criptato con password-derived key
    key_file = Path.home() / ".matriosha" / f".key_{vault_id}"
    if key_file.exists():
        master_key = derive_key(os.getenv("MATRIOSHA_UNLOCK_KEY", ""), salt)
        key_b64 = decrypt_data(master_key, key_file.read_text())
    else:
        raise KeyError(f"No key found for vault: {vault_id}")
```

---

## 🟡 MEDIUM — Edge cases

### 8. `binary_protocol.py` non gestisce version mismatch graceful

**File:** `core/binary_protocol.py`, `validate_header()`

**Problema:** Se un blocco ha `version=2` e il parser supporta solo `version=1`, `validate_header()` ritorna `False` ma non dà info sul perché. In produzione, debugging impossibile.

**Fix:** Logging dettagliato:
```python
if data["version"] > max_supported_version:
    logger.warning(f"Future protocol version {data['version']} > supported {max_supported_version}")
    return False
```

---

### 9. `security.py` non valida la lunghezza del plaintext prima di encrypt

**Problema:** AES-GCM non ha limiti teorici, ma plaintext enormi (>100MB) possono causare OOM. Nessun check preventivo.

**Fix:**
```python
MAX_PLAINTEXT_SIZE = 100 * 1024 * 1024  # 100MB
if len(plaintext) > MAX_PLAINTEXT_SIZE:
    raise ValueError(f"Plaintext too large: {len(plaintext)} bytes (max {MAX_PLAINTEXT_SIZE})")
```

---

### 10. Timestamp overflow in `binary_protocol.py`

**File:** `core/binary_protocol.py`

**Problema:** Timestamp è `uint32` (4 byte). Max valore: 4,294,967,295 = anno 2106. OK per ora, ma nel 2038 i sistemi a 32-bit avranno problemi (Y2K38 bug). Non critico oggi, ma va documentato.

---

### 11. `recall.py` non ordina i risultati per relevance_score

**File:** `cli/commands/recall.py`, riga ~55

**Problema:** I risultati di LanceDB search sono già ordinati per distanza, ma dopo il decrypt loop l'ordine potrebbe cambiare se alcuni blocchi falliscono. Nessun re-sort finale.

**Fix:**
```python
memories.sort(key=lambda m: m["relevance_score"])
```

---

### 12. Nessuna rate limiting su operazioni crypto

**Problema:** Argon2id con `memory_cost=64MB` è intenzionalmente lento (~100ms). Un attacker può fare DoS chiamando `derive_key()` ripetutamente. Nessun throttling a livello applicativo.

**Fix:** Rate limiter semplice:
```python
import time
_last_derive_time = 0
_DERIVE_COOLDOWN = 0.5  # 500ms minimo tra derive

def derive_key(password, salt):
    global _last_derive_time
    now = time.time()
    if now - _last_derive_time < _DERIVE_COOLDOWN:
        time.sleep(_DERIVE_COOLDOWN - (now - _last_derive_time))
    _last_derive_time = time.time()
    # ... resto della funzione
```

---

## 🟢 LOW — Miglioramenti architetturali

### 13. `sync_cmd()` è uno stub vuoto

**File:** `cli/commands/sync.py`

**Problema:** Il comando principale per il cloud sync non è implementato. La spec P5 lo richiede.

**Stato:** Noto, in backlog.

---

### 14. `mcp_server.py` non letto nell'audit

**File:** `mcp_server.py`

**Azione richiesta:** Leggere e auditare separatamente.

---

### 15. Nessuna migrazione DB automatizzata

**File:** `migrations/001_create_tables.sql`, `002_rls_policies.sql`

**Problema:** Le migrazioni SQL esistono ma non c'è script automatico per applicarle. Deploy manuale = errore umano.

**Fix:** Script `scripts/apply-migrations.sh`:
```bash
#!/bin/bash
supabase db push --db-url "$SUPABASE_CONNECTION_STRING"
echo "Migrations applied"
```

---

### 16. Dashboard Next.js non ha `.env.local`

**File:** `dashboard/.env.local` — NON ESISTE

**Problema:** Il frontend non può connettersi a Supabase/Clerk senza env vars.

**Fix:** Generare da `push-secrets.sh`:
```bash
cat > dashboard/.env.local <<EOF
NEXT_PUBLIC_SUPABASE_URL=$SUPABASE_URL
NEXT_PUBLIC_SUPABASE_ANON_KEY=$SUPABASE_ANON_KEY
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=$CLERK_PUBLISHABLE_KEY
CLERK_SECRET_KEY=$CLERK_SECRET_KEY
EOF
```

---

### 17. `requirements.txt` non pinned per tutte le dipendenze

**File:** `requirements.txt`

**Problema:** Alcune dipendenze transitive non sono pinned. `pip install` può installare versioni diverse in ambienti diversi.

**Fix:** Generare `requirements-lock.txt` con `pip freeze` dopo test completi.

---

## 📊 Riepilogo

| Severity | Count | Items |
|----------|-------|-------|
| 🔴 CRITICAL | 3 | GCP auth mancante, SQL injection, Merkle race condition |
| 🟠 HIGH | 4 | Merkle non verificato, leaf_id_hash wrong, HNSW recreate, keyring headless |
| 🟡 MEDIUM | 5 | Version mismatch, plaintext size, timestamp overflow, recall sort, rate limit |
| 🟢 LOW | 4 | Sync stub, MCP unread, migrations manual, dashboard env |

**Totale:** 16 issues trovati

---

## ✅ Azioni immediate (priorità)

1. **Configurare GCP auth sul server** → `GOOGLE_APPLICATION_CREDENTIALS` env var
2. **Fix SQL injection in `brain.py`** → validazione regex stretta
3. **Implementare Merkle verification in `recall.py`** → rimuovere hardcoded `True`
4. **Fix leaf_id_hash calculation** → hash su ciphertext+nonce+tag, non solo ciphertext
5. **Generare `dashboard/.env.local`** → da `push-secrets.sh`

Dopo questi 5 fix, Matriosha è ready per testing end-to-end.
