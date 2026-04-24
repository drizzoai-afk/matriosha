from __future__ import annotations

import io
import json

from PIL import Image
from docx import Document
from openpyxl import Workbook
from pypdf import PdfWriter

from matriosha.core.interpreter import InterpreterBounds, decode_semantic_content


def test_decode_text_json_and_csv_contract_fields() -> None:
    payload = json.dumps({"hello": "world", "n": 1}).encode("utf-8")
    semantic = decode_semantic_content(payload, {"mime_type": "application/json", "filename": "sample.json"})

    assert semantic["kind"] == "text"
    assert semantic["mime_type"] == "application/json"
    assert semantic["filename"] == "sample.json"
    assert isinstance(semantic["text"], str)
    assert isinstance(semantic["tables"], list)
    assert isinstance(semantic["metadata"], dict)
    assert isinstance(semantic["warnings"], list)
    assert isinstance(semantic["preview"], str)
    assert semantic["metadata"]["json_valid"] is True

    csv_semantic = decode_semantic_content(
        b"name,score\nalice,10\nbob,9\n",
        {"mime_type": "text/csv", "filename": "scores.csv"},
    )
    assert csv_semantic["kind"] == "text"
    assert len(csv_semantic["tables"]) == 1
    assert csv_semantic["tables"][0]["row_count"] == 3


def test_decode_pdf_docx_xlsx_best_effort() -> None:
    pdf_writer = PdfWriter()
    pdf_writer.add_blank_page(width=200, height=200)
    pdf_buffer = io.BytesIO()
    pdf_writer.write(pdf_buffer)
    pdf_semantic = decode_semantic_content(pdf_buffer.getvalue(), {"filename": "f.pdf"})
    assert pdf_semantic["kind"] == "pdf"
    assert pdf_semantic["metadata"]["page_count"] == 1

    doc = Document()
    doc.add_paragraph("alpha section")
    doc.add_paragraph("beta section")
    doc_buffer = io.BytesIO()
    doc.save(doc_buffer)
    doc_semantic = decode_semantic_content(
        doc_buffer.getvalue(),
        {"filename": "memo.docx"},
    )
    assert doc_semantic["kind"] == "document"
    assert "alpha section" in doc_semantic["text"]

    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["id", "value"])
    ws.append([1, "A"])
    xlsx_buffer = io.BytesIO()
    wb.save(xlsx_buffer)
    xlsx_semantic = decode_semantic_content(
        xlsx_buffer.getvalue(),
        {"filename": "table.xlsx"},
    )
    assert xlsx_semantic["kind"] == "table"
    assert xlsx_semantic["metadata"]["sheet_count"] == 1
    assert xlsx_semantic["tables"][0]["column_count"] >= 2


def test_decode_image_ocr_and_unknown_fallback(monkeypatch) -> None:
    monkeypatch.setattr("matriosha.core.interpreter.pytesseract.image_to_string", lambda _img: "OCR text here")

    img = Image.new("RGB", (40, 30), color=(255, 255, 255))
    img_buf = io.BytesIO()
    img.save(img_buf, format="PNG")
    image_semantic = decode_semantic_content(img_buf.getvalue(), {"filename": "image.png"})

    assert image_semantic["kind"] == "image"
    assert image_semantic["metadata"]["width"] == 40
    assert image_semantic["metadata"]["height"] == 30
    assert "OCR text here" in image_semantic["text"]

    unknown = decode_semantic_content(b"\x00\x01\x02\xff\xf0", {"filename": "blob.bin"})
    assert unknown["kind"] == "binary"
    assert unknown["metadata"]["input_bytes"] == 5
    assert unknown["warnings"]


def test_interpreter_bounds_are_deterministic() -> None:
    semantic = decode_semantic_content(
        ("A" * 1000).encode("utf-8"),
        {"mime_type": "text/plain", "filename": "big.txt"},
        bounds=InterpreterBounds(max_text_chars=120, max_preview_chars=20),
    )

    assert len(semantic["text"]) == 120
    assert len(semantic["preview"]) <= 20
    assert any("truncated" in warning for warning in semantic["warnings"])
