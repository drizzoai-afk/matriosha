from __future__ import annotations

import io
from typing import Any

from openpyxl import Workbook
from pypdf import PdfWriter

from matriosha.core.interpreter import decode_semantic_content
from matriosha.core.interpreter_plugins import REGISTRY, list_decoders, register_decoder, reset_default_decoders_for_tests


class _CustomRuntimeDecoder:
    name = "test.runtime.custom"

    def supports(self, mime_type: str, filename: str | None, metadata: dict[str, Any]) -> bool:
        return mime_type == "application/x-custom"

    def decode(self, raw: bytes, metadata: dict[str, Any], bounds: Any) -> dict[str, Any]:
        return {
            "kind": "text",
            "text": f"custom::{raw.decode('utf-8', errors='replace')}",
            "metadata": {"decoder": self.name},
            "warnings": [],
        }


class _AlphaDecoder:
    name = "test.runtime.alpha"

    def supports(self, mime_type: str, filename: str | None, metadata: dict[str, Any]) -> bool:
        return mime_type == "text/plain"

    def decode(self, raw: bytes, metadata: dict[str, Any], bounds: Any) -> dict[str, Any]:
        return {"kind": "text", "text": "alpha", "metadata": {}, "warnings": []}


class _BetaDecoder:
    name = "test.runtime.beta"

    def supports(self, mime_type: str, filename: str | None, metadata: dict[str, Any]) -> bool:
        return mime_type == "text/plain"

    def decode(self, raw: bytes, metadata: dict[str, Any], bounds: Any) -> dict[str, Any]:
        return {"kind": "text", "text": "beta", "metadata": {}, "warnings": []}


class _FakeEntryPoint:
    def __init__(self, name: str, loader: Any) -> None:
        self.name = name
        self._loader = loader

    def load(self) -> Any:
        return self._loader


class _FakeEntryPoints:
    def __init__(self, eps: list[_FakeEntryPoint]) -> None:
        self._eps = eps

    def select(self, *, group: str) -> list[_FakeEntryPoint]:
        if group == "matriosha.decoders":
            return list(self._eps)
        return []


def setup_function() -> None:
    reset_default_decoders_for_tests()


def teardown_function() -> None:
    reset_default_decoders_for_tests()


def test_builtins_decoding_remains_compatible_for_common_types() -> None:
    text_semantic = decode_semantic_content(b"hello", {"mime_type": "text/plain", "filename": "a.txt"})
    assert text_semantic["kind"] == "text"
    assert text_semantic["text"] == "hello"

    pdf_writer = PdfWriter()
    pdf_writer.add_blank_page(width=200, height=200)
    pdf_buffer = io.BytesIO()
    pdf_writer.write(pdf_buffer)
    pdf_semantic = decode_semantic_content(pdf_buffer.getvalue(), {"filename": "f.pdf"})
    assert pdf_semantic["kind"] == "pdf"
    assert pdf_semantic["metadata"]["page_count"] == 1

    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["id", "value"])
    ws.append([1, "A"])
    xlsx_buffer = io.BytesIO()
    wb.save(xlsx_buffer)
    xlsx_semantic = decode_semantic_content(xlsx_buffer.getvalue(), {"filename": "table.xlsx"})
    assert xlsx_semantic["kind"] == "table"
    assert xlsx_semantic["metadata"]["sheet_count"] == 1


def test_runtime_registration_custom_decoder_works() -> None:
    register_decoder(_CustomRuntimeDecoder())
    semantic = decode_semantic_content(
        b"payload",
        {"mime_type": "application/x-custom", "filename": "x.custom"},
    )
    assert semantic["kind"] == "text"
    assert semantic["text"] == "custom::payload"
    assert semantic["metadata"]["decoder"] == "test.runtime.custom"


def test_entry_point_discovery_loads_mock_plugin(monkeypatch) -> None:
    class EntryPointDecoder:
        name = "test.entrypoint.mock"

        def supports(self, mime_type: str, filename: str | None, metadata: dict[str, Any]) -> bool:
            return mime_type == "application/x-entry"

        def decode(self, raw: bytes, metadata: dict[str, Any], bounds: Any) -> dict[str, Any]:
            return {"kind": "text", "text": "entry-point", "metadata": {}, "warnings": []}

    monkeypatch.setattr(
        "matriosha.core.interpreter_plugins.importlib_metadata.entry_points",
        lambda: _FakeEntryPoints([_FakeEntryPoint("mock", EntryPointDecoder)]),
    )

    reset_default_decoders_for_tests()
    semantic = decode_semantic_content(
        b"ignored",
        {"mime_type": "application/x-entry", "filename": "ep.bin"},
    )
    assert semantic["text"] == "entry-point"

    names = [d["name"] for d in list_decoders()]
    assert "test.entrypoint.mock" in names


def test_plugin_load_failure_is_non_fatal_and_warns(monkeypatch) -> None:
    def broken_loader() -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "matriosha.core.interpreter_plugins.importlib_metadata.entry_points",
        lambda: _FakeEntryPoints([_FakeEntryPoint("broken", broken_loader)]),
    )

    reset_default_decoders_for_tests()
    semantic = decode_semantic_content(
        b"hello",
        {"mime_type": "text/plain", "filename": "a.txt"},
    )

    assert semantic["kind"] == "text"
    assert any("failed loading decoder plugin entry-point 'broken'" in w for w in semantic["warnings"])


def test_deterministic_precedence_with_usage_priority() -> None:
    register_decoder(_AlphaDecoder())
    register_decoder(_BetaDecoder())

    first = decode_semantic_content(b"x", {"mime_type": "text/plain", "filename": "a.txt"})
    assert first["text"] == "alpha"
    assert any("multiple decoder plugins matched" in w for w in first["warnings"])

    REGISTRY.increment_usage("test.runtime.beta")
    REGISTRY.increment_usage("test.runtime.beta")

    second = decode_semantic_content(b"x", {"mime_type": "text/plain", "filename": "a.txt"})
    assert second["text"] == "beta"


def test_binary_fallback_remains_functional() -> None:
    semantic = decode_semantic_content(b"\x00\x01\x02\xff", {"filename": "blob.bin"})
    assert semantic["kind"] == "binary"
    assert semantic["metadata"].get("binary_preview_hex")
    assert any("unknown binary payload" in w for w in semantic["warnings"])


def test_usage_tracking_and_reset() -> None:
    register_decoder(_CustomRuntimeDecoder())
    decode_semantic_content(b"one", {"mime_type": "application/x-custom", "filename": "x.custom"})
    decode_semantic_content(b"two", {"mime_type": "application/x-custom", "filename": "x.custom"})

    decoder_info = {item["name"]: item for item in list_decoders()}
    assert decoder_info["test.runtime.custom"]["usage_count"] == 2

    reset_default_decoders_for_tests()
    decoder_info_after_reset = {item["name"]: item for item in list_decoders()}
    assert "test.runtime.custom" not in decoder_info_after_reset
    assert decoder_info_after_reset["builtin.text"]["usage_count"] == 0


def test_more_used_plugin_gets_priority() -> None:
    register_decoder(_AlphaDecoder())
    register_decoder(_BetaDecoder())

    REGISTRY.increment_usage("test.runtime.beta")
    semantic = decode_semantic_content(b"x", {"mime_type": "text/plain", "filename": "a.txt"})

    assert semantic["text"] == "beta"
