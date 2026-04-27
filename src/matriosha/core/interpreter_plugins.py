"""Decoder plugin registry and discovery for semantic interpreter."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata as importlib_metadata
from typing import Any, Callable, Protocol, runtime_checkable


@runtime_checkable
class DecoderPlugin(Protocol):
    """Protocol all decoder plugins must satisfy."""

    name: str

    def supports(self, mime_type: str, filename: str | None, metadata: dict[str, Any]) -> bool:
        """Return True if this decoder can handle the payload metadata."""

    def decode(self, raw: bytes, metadata: dict[str, Any], bounds: Any) -> dict[str, Any]:
        """Decode payload bytes and return semantic patch fields."""


@dataclass
class _PluginRecord:
    plugin: DecoderPlugin
    source: str
    registration_order: int


_SOURCE_PRIORITY = {
    "runtime": 0,
    "entry_point": 1,
    "builtin": 2,
    "fallback": 3,
}


class Registry:
    """Central decoder registry with adaptive usage-based ordering."""

    def __init__(self) -> None:
        self._records: dict[str, _PluginRecord] = {}
        self._usage_counts: dict[str, int] = {}
        self._counter: int = 0
        self._warnings: list[str] = []
        self._defaults_factory: Callable[[], list[tuple[DecoderPlugin, str]]] | None = None
        self._entry_points_loaded = False

    def set_default_factory(self, factory: Callable[[], list[tuple[DecoderPlugin, str]]]) -> None:
        self._defaults_factory = factory

    def register_decoder(self, plugin: DecoderPlugin, *, replace: bool = False, source: str = "runtime") -> None:
        name = getattr(plugin, "name", None)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("decoder plugin must define non-empty string 'name'")

        normalized_name = name.strip()
        if normalized_name in self._records and not replace:
            raise ValueError(f"decoder plugin '{normalized_name}' already registered")

        if source not in _SOURCE_PRIORITY:
            raise ValueError(f"unknown plugin source '{source}'")

        existing = self._records.get(normalized_name)
        if existing and replace:
            # Keep registration order stable for deterministic replacement semantics.
            order = existing.registration_order
        else:
            self._counter += 1
            order = self._counter

        self._records[normalized_name] = _PluginRecord(
            plugin=plugin,
            source=source,
            registration_order=order,
        )
        self._usage_counts.setdefault(normalized_name, 0)

    def unregister_decoder(self, name: str) -> None:
        self._records.pop(name, None)
        self._usage_counts.pop(name, None)

    def list_decoders(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for name, record in self._sorted_records():
            items.append(
                {
                    "name": name,
                    "source": record.source,
                    "usage_count": self._usage_counts.get(name, 0),
                    "registration_order": record.registration_order,
                }
            )
        return items

    def usage_count(self, name: str) -> int:
        return self._usage_counts.get(name, 0)

    def increment_usage(self, name: str) -> None:
        if name in self._records:
            self._usage_counts[name] = self._usage_counts.get(name, 0) + 1

    def get_matching_decoders(
        self,
        mime_type: str,
        filename: str | None,
        metadata: dict[str, Any],
    ) -> list[DecoderPlugin]:
        self.discover_entry_point_decoders()
        matching: list[tuple[str, _PluginRecord]] = []
        for name, record in self._sorted_records():
            try:
                if record.plugin.supports(mime_type, filename, metadata):
                    matching.append((name, record))
            except Exception as exc:  # noqa: BLE001
                self._warnings.append(
                    f"decoder plugin '{name}' supports() failed and was skipped: {type(exc).__name__}: {exc}"
                )
        return [record.plugin for _, record in matching]

    def discover_entry_point_decoders(self) -> None:
        if self._entry_points_loaded:
            return
        self._entry_points_loaded = True

        try:
            available = importlib_metadata.entry_points()
            entry_points = available.select(group="matriosha.decoders")
        except Exception as exc:  # noqa: BLE001
            self._warnings.append(
                f"decoder entry-point discovery failed: {type(exc).__name__}: {exc}"
            )
            return

        for entry_point in entry_points:
            try:
                loaded = entry_point.load()
                plugin = loaded() if isinstance(loaded, type) else loaded
                self.register_decoder(plugin, source="entry_point")
            except Exception as exc:  # noqa: BLE001
                self._warnings.append(
                    f"failed loading decoder plugin entry-point '{entry_point.name}': {type(exc).__name__}: {exc}"
                )

    def reset_default_decoders_for_tests(self) -> None:
        self._records.clear()
        self._usage_counts.clear()
        self._warnings.clear()
        self._counter = 0
        self._entry_points_loaded = False

        if self._defaults_factory is not None:
            for plugin, source in self._defaults_factory():
                self.register_decoder(plugin, source=source)

    def pull_warnings(self) -> list[str]:
        warnings = list(self._warnings)
        self._warnings.clear()
        return warnings

    def _sorted_records(self) -> list[tuple[str, _PluginRecord]]:
        items = list(self._records.items())
        items.sort(
            key=lambda item: (
                _SOURCE_PRIORITY[item[1].source],
                -self._usage_counts.get(item[0], 0),
                item[1].registration_order,
                item[0],
            )
        )
        return items


REGISTRY = Registry()


def register_decoder(plugin: DecoderPlugin, *, replace: bool = False) -> None:
    REGISTRY.register_decoder(plugin, replace=replace, source="runtime")


def unregister_decoder(name: str) -> None:
    REGISTRY.unregister_decoder(name)


def list_decoders() -> list[dict[str, Any]]:
    return REGISTRY.list_decoders()


def reset_default_decoders_for_tests() -> None:
    REGISTRY.reset_default_decoders_for_tests()
