# Decoder Plugins (P6.8)

Matriosha supports semantic decoder extensions through a plugin registry in `core/interpreter_plugins.py`.

## Interface contract

Every decoder plugin must provide:

- `name: str` (stable unique ID)
- `supports(mime_type: str, filename: str | None, metadata: dict) -> bool`
- `decode(raw: bytes, metadata: dict, bounds: InterpreterBounds) -> dict`

`decode()` must return a semantic patch dictionary. Supported keys:

- `kind` (e.g. `pdf`, `text`, `binary`)
- `text` (string)
- `tables` (list)
- `metadata` (dict)
- `warnings` (list[str])

The final output contract remains unchanged:
`kind`, `mime_type`, `filename`, `text`, `tables`, `metadata`, `warnings`, `preview`.

## Priority and routing

Matching decoders are chosen with deterministic first-match routing:

1. Runtime-registered plugins (`register_decoder`)
2. Entry-point plugins (`matriosha.decoders`)
3. Built-in decoders
4. Built-in binary fallback (always last)

Inside each tier, ordering is adaptive and deterministic:

- Higher successful usage count wins
- Tie-breaker: registration order
- Final tie-breaker: name

When multiple plugins match, Matriosha adds a warning indicating the selected plugin and skipped alternatives.

## Minimal plugin example

```python
from typing import Any

class MyMarkdownDecoder:
    name = "acme.markdown_plus"

    def supports(self, mime_type: str, filename: str | None, metadata: dict[str, Any]) -> bool:
        return mime_type == "text/markdown" or (filename or "").lower().endswith(".md")

    def decode(self, raw: bytes, metadata: dict[str, Any], bounds: Any) -> dict[str, Any]:
        text = raw.decode("utf-8", errors="replace")
        return {
            "kind": "text",
            "text": text,
            "metadata": {"plugin": self.name},
            "warnings": [],
        }
```

## Entry-point declaration (`pyproject.toml`)

```toml
[project.entry-points."matriosha.decoders"]
acme_markdown = "acme_matriosha_plugins:MyMarkdownDecoder"
```

The object can be either:

- A class (Matriosha will instantiate it with no args), or
- A pre-instantiated plugin object

## Safety and bounds expectations

Plugins must:

- Respect `InterpreterBounds` limits when extracting content
- Avoid unbounded memory growth and excessive CPU loops
- Return warnings instead of raising for recoverable parser issues
- Treat untrusted input as hostile

If `decode()` raises, Matriosha falls back to safe binary decoding and preserves compatibility.

## Compatibility/versioning

- Target the active semantic contract in `SPECIFICATION.md` section 4.5
- Keep plugin `name` stable across releases (used in diagnostics and usage tracking)
- Use additive metadata keys to avoid breaking downstream tools

## Troubleshooting plugin load failures

Entry-point loading is non-fatal. If a plugin import/load fails:

- Matriosha continues running with remaining decoders
- A warning is added to semantic output (`warnings`)

Common causes:

- Missing plugin dependency
- Import error in plugin module
- Plugin object missing required interface fields/methods

## Runtime API surface

- `register_decoder(plugin, replace=False)`
- `unregister_decoder(name)`
- `list_decoders()`
- `reset_default_decoders_for_tests()`

These live in `core/interpreter_plugins.py`.
