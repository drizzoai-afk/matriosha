from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(payload))

    data = normalized.get("data", {})
    if isinstance(data, dict):
        if "memory_id" in data:
            data["memory_id"] = "<MEMORY_ID>"
        if "path" in data:
            data["path"] = "<MEMORY_PATH>"
        if "merkle_root" in data:
            data["merkle_root"] = "<MERKLE_ROOT>"

        items = data.get("items")
        if isinstance(items, list):
            allowed_item_keys = {
                "children",
                "created_at",
                "encoding",
                "hash_algo",
                "memory_id",
                "merkle_leaf",
                "merkle_root",
                "mode",
                "source",
                "tags",
                "vector_dim",
            }
            for item in items:
                if isinstance(item, dict):
                    block_count = 1
                    try:
                        block_count = max(1, int(item.get("blocks") or 1))
                    except Exception:
                        block_count = 1

                    for key in list(item.keys()):
                        if key not in allowed_item_keys:
                            item.pop(key, None)
                    item.setdefault("children", None)
                    item.setdefault("encoding", "base64")
                    item.setdefault("hash_algo", "sha256")
                    item.setdefault("mode", "local")
                    item.setdefault("source", "cli")
                    item.setdefault("vector_dim", 384)
                    item["memory_id"] = "<MEMORY_ID>"
                    item["created_at"] = "<TIMESTAMP>"
                    item["merkle_root"] = "<MERKLE_ROOT>"
                    leaves = item.get("merkle_leaf")
                    if isinstance(leaves, list):
                        item["merkle_leaf"] = ["<MERKLE_LEAF>"] * len(leaves)
                    else:
                        item["merkle_leaf"] = ["<MERKLE_LEAF>"] * block_count

        results = data.get("results")
        if isinstance(results, list):
            for result in results:
                if isinstance(result, dict):
                    result["memory_id"] = "<MEMORY_ID>"
                    result["created_at"] = "<TIMESTAMP>"

    return normalized


@pytest.mark.integration
def test_local_happy_path_end_to_end(initialized_vault, cli_runner) -> None:
    remembered_ids: list[str] = []
    files = [
        ("pride_and_prejudice_excerpt.txt", "txt"),
        ("knowledge_base.md", "md"),
        ("countries.csv", "csv"),
    ]

    for filename, tag in files:
        remember = cli_runner.invoke(
            [
                "memory",
                "remember",
                "--file",
                str(FIXTURES_DIR / filename),
                "--tag",
                "p71a",
                "--tag",
                tag,
                "--json",
            ]
        )
        assert remember.exit_code == 0, remember.stdout
        payload = json.loads(remember.stdout)
        remembered_ids.append(payload["data"]["memory_id"])

    listed = cli_runner.invoke(["memory", "list", "--tag", "p71a", "--json"])
    assert listed.exit_code == 0, listed.stdout
    listed_payload = json.loads(listed.stdout)
    assert len(listed_payload["data"]["items"]) >= 3

    searched = cli_runner.invoke(["memory", "search", "DataFrame", "--k", "5", "--json"])
    assert searched.exit_code == 0, searched.stdout
    search_payload = json.loads(searched.stdout)
    assert search_payload["data"]["results"]

    recalled = cli_runner.invoke(["memory", "recall", remembered_ids[0], "--json"])
    assert recalled.exit_code == 0, recalled.stdout
    recalled_payload = json.loads(recalled.stdout)
    assert recalled_payload["data"]["memory_id"] == remembered_ids[0]
    assert "semantic" in recalled_payload["data"]

    deleted = cli_runner.invoke(["memory", "delete", remembered_ids[1], "--yes", "--json"])
    assert deleted.exit_code == 0, deleted.stdout

    verify = cli_runner.invoke(["vault", "verify", "--deep", "--json"])
    assert verify.exit_code == 0, verify.stdout
    verify_payload = json.loads(verify.stdout)
    assert verify_payload["failed"] == []

    remembered_payload = _normalize_payload(json.loads(remember.stdout))
    listed_normalized = _normalize_payload(listed_payload)
    searched_normalized = _normalize_payload(search_payload)
    recalled_normalized = _normalize_payload(recalled_payload)

    assert remembered_payload.get("status") == "ok"
    assert remembered_payload.get("operation") == "memory.remember"
    assert listed_normalized.get("status") == "ok"
    assert listed_normalized.get("operation") == "memory.list"
    assert searched_normalized.get("status") == "ok"
    assert searched_normalized.get("operation") == "memory.search"
    assert recalled_normalized.get("status") == "ok"
    assert recalled_normalized.get("operation") == "memory.recall"
    assert verify_payload.get("ok", 0) >= 1
