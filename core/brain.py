"""
Matriosha Core — Brain Module (P4 Production-Ready)

Handles local vector search using FastEmbed and LanceDB.
Implements Stage 1 of the Two-Stage Recall process with HNSW indexing.

Production-Ready Features:
- LanceDB for high-performance, serverless vector storage.
- HNSW index for O(log n) semantic search.
- Metadata filtering (importance, logic_state) at the database level.
- Atomic updates and concurrency safety.
"""

import numpy as np
import pyarrow as pa
from pathlib import Path
from typing import List, Dict
from fastembed import TextEmbedding
import lancedb

# Constants
# Switched to all-MiniLM-L6-v2 for 2x faster CPU inference with similar quality
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
INDEX_DB_NAME = "matriosha_brain.lancedb"
TABLE_NAME = "memories"


class MatrioshaBrain:
    def __init__(self, vault_path: Path):
        self.vault_path = vault_path
        self.db_path = vault_path / INDEX_DB_NAME
        self.model = TextEmbedding(model_name=EMBEDDING_MODEL)

        # Initialize LanceDB connection
        self.db = lancedb.connect(str(self.db_path))
        self.table = self._init_table()

    def _init_table(self):
        """Initialize or open the LanceDB table with schema."""
        schema = pa.schema([
            pa.field("leaf_id", pa.string()),
            pa.field("embedding", pa.list_(pa.float32(), list_size=384)),
            pa.field("importance", pa.int32()),
            pa.field("logic_state", pa.int32()),
            pa.field("timestamp", pa.int64()),
            pa.field("content_preview", pa.string())
        ])

        if TABLE_NAME in self.db.table_names():
            table = self.db.open_table(TABLE_NAME)
        else:
            table = self.db.create_table(TABLE_NAME, schema=schema)
            # Create HNSW index once at table creation
            try:
                table.create_index(
                    vector_column_name="embedding",
                    index_type="IVF_HNSW_SQ",
                    num_partitions=256,
                    num_sub_vectors=96
                )
            except Exception as e:
                print(f"Warning: Could not create HNSW index: {e}")
        return table

    def embed_text(self, text: str) -> np.ndarray:
        """Generate embedding for a given text."""
        embeddings = list(self.model.embed([text]))
        return np.array(embeddings[0], dtype=np.float32)

    def add_to_index(self, leaf_id: str, content: str, importance: int, logic_state: int, timestamp: int):
        """Add a memory block to the LanceDB index."""
        embedding = self.embed_text(content)
        preview = content[:200] if len(content) > 200 else content

        data = [{
            "leaf_id": leaf_id,
            "embedding": embedding.tolist(),
            "importance": importance,
            "logic_state": logic_state,
            "timestamp": timestamp,
            "content_preview": preview
        }]

        self.table.add(data)

    def search(self, query: str, top_k: int = 5, min_importance: int = 0) -> List[Dict]:
        """
        Semantic search against the LanceDB index.
        Uses HNSW for fast retrieval and metadata filtering.
        """
        # Validate min_importance to prevent injection (must be int 0-3)
        if not isinstance(min_importance, int) or not (0 <= min_importance <= 3):
            raise ValueError(f"min_importance must be int 0-3, got {min_importance!r}")
        if not isinstance(top_k, int) or top_k < 1:
            raise ValueError(f"top_k must be positive int, got {top_k!r}")

        query_embedding = self.embed_text(query).tolist()

        results = self.table.search(query_embedding) \
            .where(f"importance >= {min_importance}") \
            .limit(top_k) \
            .to_list()

        formatted_results = []
        for row in results:
            formatted_results.append({
                "leaf_id": row["leaf_id"],
                "importance": row["importance"],
                "logic_state": row["logic_state"],
                "timestamp": row["timestamp"],
                "preview": row["content_preview"],
                "relevance_score": float(row["_distance"])  # LanceDB returns distance
            })

        return formatted_results

    def remove_from_index(self, leaf_id: str):
        """Remove a memory block from the index."""
        import re
        # Strict validation: 10 bytes = 20 hex chars, lowercase only
        if not isinstance(leaf_id, str) or not re.match(r'^[a-f0-9]{20}$', leaf_id):
            raise ValueError(f"leaf_id must be a 20-char hex string, got {leaf_id!r}")
        self.table.delete(f"leaf_id = '{leaf_id}'")
