from __future__ import annotations

from pathlib import Path

import pytest

from matriosha.core.interpreter import decode_semantic_content


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.mark.integration
@pytest.mark.parametrize(
    ("filename", "mime_type", "expected_kind"),
    [
        ("realistic_report.pdf", "application/pdf", "pdf"),
        ("mountain_scene.jpg", "image/jpeg", "image"),
        ("knowledge_base.md", "text/markdown", "text"),
        ("countries.csv", "text/csv", "text"),
    ],
)
def test_semantic_extraction_rich_output(
    filename: str, mime_type: str, expected_kind: str, snapshot
) -> None:
    payload = (FIXTURES_DIR / filename).read_bytes()
    semantic = decode_semantic_content(payload, {"filename": filename, "mime_type": mime_type})

    assert semantic["kind"] == expected_kind
    assert set(semantic.keys()) >= {
        "kind",
        "mime_type",
        "filename",
        "text",
        "tables",
        "metadata",
        "warnings",
        "preview",
    }

    if filename.endswith(".pdf"):
        assert semantic["metadata"].get("page_count", 0) >= 1
    elif filename.endswith(".jpg"):
        assert semantic["metadata"].get("width", 0) > 0
        assert semantic["metadata"].get("height", 0) > 0
    elif filename.endswith(".md"):
        assert semantic["metadata"].get("line_count", 0) > 0
        assert "pandas" in semantic["text"].lower()
    elif filename.endswith(".csv"):
        assert semantic["tables"]
        assert semantic["tables"][0].get("row_count", 0) > 0

    snapshot_payload = {
        "filename": filename,
        "kind": semantic["kind"],
        "mime_type": semantic["mime_type"],
        "metadata": semantic["metadata"],
        "warnings": semantic["warnings"],
        "preview": semantic["preview"],
    }
    assert snapshot_payload == snapshot
