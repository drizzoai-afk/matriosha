"""
Matriosha Core — Brain Module (P4)

Handles local vector search using FastEmbed for semantic recall.
Implements Stage 1 of the Two-Stage Recall process:
1. Generate query embedding.
2. Search local index (SQLite/JSON) for Top-K Leaf IDs.
3. Return metadata for Stage 2 (Fetch & Decrypt).

Production-Ready Features:
- BAAI/bge-small-en-v1.5 model (384 dimensions, optimized for speed).
- Persistent local index with atomic writes.
- Cosine similarity scoring.
"""

import os
import json
import sqlite3
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from fastembed import TextEmbedding
from datetime import datetime

# Constants
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
INDEX_DB_NAME = "matriosha_index.db"


class MatrioshaBrain:
    def __init__(self, vault_path: Path):
        self.vault_path = vault_path
        self.index_path = vault_path / INDEX_DB_NAME
        self.model = TextEmbedding(model_name=EMBEDDING_MODEL)
        self._init_db()

    def _init_db(self):
        """Initialize SQLite database for vector indexing."""
        conn = sqlite3.connect(str(self.index_path))
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memory_index (
                leaf_id TEXT PRIMARY KEY,
                embedding BLOB NOT NULL,
                importance INTEGER,
                logic_state INTEGER,
                timestamp INTEGER,
                content_preview TEXT
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_importance ON memory_index(importance)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON memory_index(timestamp)")
        conn.commit()
        conn.close()

    def embed_text(self, text: str) -> np.ndarray:
        """Generate embedding for a given text."""
        embeddings = list(self.model.embed([text]))
        return np.array(embeddings[0], dtype=np.float32)

    def add_to_index(self, leaf_id: str, content: str, importance: int, logic_state: int, timestamp: int):
        """Add a memory block to the local vector index."""
        embedding = self.embed_text(content)
        preview = content[:200] if len(content) > 200 else content
        
        conn = sqlite3.connect(str(self.index_path))
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO memory_index 
            (leaf_id, embedding, importance, logic_state, timestamp, content_preview)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (leaf_id, embedding.tobytes(), importance, logic_state, timestamp, preview))
        conn.commit()
        conn.close()

    def search(self, query: str, top_k: int = 5, min_importance: int = 0) -> List[Dict]:
        """
        Semantic search against the local index.
        Returns Top-K Leaf IDs with metadata and relevance scores.
        """
        query_embedding = self.embed_text(query)
        
        conn = sqlite3.connect(str(self.index_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Retrieve all candidates (for MVP; production would use HNSW/IVFFlat)
        cursor.execute("SELECT * FROM memory_index WHERE importance >= ?", (min_importance,))
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return []

        # Calculate cosine similarity in-memory
        results = []
        for row in rows:
            stored_embedding = np.frombuffer(row['embedding'], dtype=np.float32)
            similarity = np.dot(query_embedding, stored_embedding) / (
                np.linalg.norm(query_embedding) * np.linalg.norm(stored_embedding)
            )
            
            results.append({
                "leaf_id": row['leaf_id'],
                "importance": row['importance'],
                "logic_state": row['logic_state'],
                "timestamp": row['timestamp'],
                "preview": row['content_preview'],
                "relevance_score": float(similarity)
            })

        # Sort by relevance and return Top-K
        results.sort(key=lambda x: x['relevance_score'], reverse=True)
        return results[:top_k]

    def remove_from_index(self, leaf_id: str):
        """Remove a memory block from the index (for deletion/archiving)."""
        conn = sqlite3.connect(str(self.index_path))
        cursor = conn.cursor()
        cursor.execute("DELETE FROM memory_index WHERE leaf_id = ?", (leaf_id,))
        conn.commit()
        conn.close()
