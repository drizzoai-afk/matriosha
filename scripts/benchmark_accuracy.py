"""
Matriosha Accuracy Benchmark — Recall@K & MRR

Measures the retrieval quality of the semantic search engine.
Uses a predefined set of queries and expected 'golden' memories.
"""

import os
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = '/home/ubuntu/.matriosha/gcp-sa-key.json'
os.environ['GCP_PROJECT'] = 'matriosha'

from core.brain import MatrioshaBrain
from cli.utils.config import load_config

# Golden Dataset: Query -> Expected Leaf ID (or unique content substring)
GOLDEN_DATASET = [
    {
        "query": "encryption algorithm",
        "expected_content": "AES-256-GCM",
        "description": "Should find the security spec memory"
    },
    {
        "query": "web framework stack",
        "expected_content": "Next.js",
        "description": "Should find the tech stack memory"
    },
    {
        "query": "database provider",
        "expected_content": "Supabase",
        "description": "Should find the DB/Auth memory"
    },
    {
        "query": "vector search engine",
        "expected_content": "LanceDB",
        "description": "Should find the vector DB memory"
    },
    {
        "query": "cold storage solution",
        "expected_content": "Cloudflare R2",
        "description": "Should find the backup storage memory"
    }
]

def run_accuracy_benchmark(vault_path_str="/tmp/matriosha-bench-v2"):
    vault_path = Path(vault_path_str)
    brain = MatrioshaBrain(vault_path)
    
    total_queries = len(GOLDEN_DATASET)
    recall_at_1 = 0
    recall_at_3 = 0
    reciprocal_ranks = []

    print(f"\n🎯 Running Accuracy Benchmark on {total_queries} queries...")
    print("-" * 60)

    for item in GOLDEN_DATASET:
        query = item["query"]
        expected = item["expected_content"]
        
        # Search top 3
        results = brain.search(query=query, top_k=3, min_importance=0)
        
        found_at = None
        for i, res in enumerate(results):
            # Fetch block to check content (since brain.search only returns metadata)
            leaf_id = res["leaf_id"]
            block_file = vault_path / f"{leaf_id}.bin"
            if block_file.exists():
                from core.security import retrieve_key_vault
                from core.binary_protocol import unpack_header, HEADER_SIZE
                import base64, json
                
                key = retrieve_key_vault(vault_path.name)
                data = block_file.read_bytes()
                header = unpack_header(data[:HEADER_SIZE])
                remaining = data[HEADER_SIZE:]
                
                ciphertext = remaining[:-28]
                nonce = remaining[-28:-16]
                tag = remaining[-16:]
                
                from core.security import decrypt_data
                plaintext = decrypt_data(
                    key, 
                    base64.b64encode(ciphertext).decode(),
                    base64.b64encode(nonce).decode(),
                    base64.b64encode(tag).decode()
                )
                content = json.loads(plaintext.decode("utf-8"))["text"]
                
                if expected in content:
                    found_at = i + 1
                    break

        # Metrics Update
        if found_at == 1:
            recall_at_1 += 1
        if found_at is not None:
            recall_at_3 += 1
            reciprocal_ranks.append(1.0 / found_at)
        else:
            reciprocal_ranks.append(0.0)
            
        status = "✅" if found_at else "❌"
        pos = f"Rank {found_at}" if found_at else "Not Found"
        print(f"{status} Query: '{query}' -> {pos}")

    # Final Report
    r_at_1 = (recall_at_1 / total_queries) * 100
    r_at_3 = (recall_at_3 / total_queries) * 100
    mrr = (sum(reciprocal_ranks) / total_queries)

    print("-" * 60)
    print(f"📊 ACCURACY REPORT:")
    print(f"  Recall@1: {r_at_1:.0f}% (Ideal: >70%)")
    print(f"  Recall@3: {r_at_3:.0f}% (Ideal: >90%)")
    print(f"  MRR:      {mrr:.2f} (Ideal: >0.7)")
    
    return {"recall_at_1": r_at_1, "recall_at_3": r_at_3, "mrr": mrr}

if __name__ == "__main__":
    run_accuracy_benchmark()
