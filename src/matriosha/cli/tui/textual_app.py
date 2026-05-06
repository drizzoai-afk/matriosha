"""Textual launcher for Matriosha.

This screen is intentionally dense and terminal-native to preserve trust and speed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.events import Resize
from textual.widgets import Input, Static

from matriosha.cli.brand.banner import BANNER


@dataclass(frozen=True)
class MenuEntry:
    label: str
    value: str


class MatrioshaTextualLauncher(App[None]):
    CSS_PATH = "launcher.tcss"

    BINDINGS = [
        ("up", "move_up", "Up"),
        ("down", "move_down", "Down"),
        ("enter", "select", "Enter"),
        ("d", "diagnostics", "Diagnostics"),
        ("p", "progress", "Progress"),
        ("s", "success", "Success"),
        ("e", "error", "Error"),
        ("w", "quota", "Quota"),
    ]

    def __init__(
        self,
        *,
        command_map: dict[str, list[str]],
        all_commands: dict[str, list[tuple[str, list[str]]]],
        menu_items: Iterable[object],
        profile_name: str,
        runtime_mode: str,
        initial_state: str = "home",
    ) -> None:
        super().__init__()
        self.command_map = command_map
        self.all_commands = all_commands
        self.profile_name = profile_name
        self.runtime_mode = runtime_mode
        self.initial_state = initial_state
        self.selected_command: list[str] | None = None

        self._home_items = [
            MenuEntry(label=getattr(item, "label"), value=getattr(item, "value"))
            for item in menu_items
        ]
        self._menu_items = list(self._home_items)
        self._selected_index = 0
        self._state = "home"
        self._search_enabled = False

    def compose(self) -> ComposeResult:
        with Container(id="root"):
            yield Static(BANNER, id="title")
            yield Static("", id="status")
            yield Input(placeholder="filter menu or commands…", id="search")
            yield Static("", id="viewport")
            yield Static("", id="footer")

    def on_mount(self) -> None:
        self._apply_mode_class()
        self._set_state(self.initial_state)

    def on_resize(self, event: Resize) -> None:
        self.set_class(event.size.width < 90, "narrow")
        if self._state == "home":
            self._render()

    def action_move_up(self) -> None:
        if self._menu_items:
            self._selected_index = (self._selected_index - 1) % len(self._menu_items)
            self._render()

    def action_move_down(self) -> None:
        if self._menu_items:
            self._selected_index = (self._selected_index + 1) % len(self._menu_items)
            self._render()

    def action_select(self) -> None:
        if not self._menu_items:
            return
        current = self._menu_items[self._selected_index]

        if self._state == "catalog" and current.value.startswith("run:"):
            self.selected_command = self._catalog_value_to_command(current.value)
            self.exit()
            return

        if self._state != "home":
            self._set_state("home")
            return

        if current.value == "all_commands":
            self._set_state("catalog")
            return

        if current.value == "quit":
            self.exit()
            return

        args = self.command_map.get(current.value)
        if args:
            self.selected_command = args
            self.exit()

    def action_quit_app(self) -> None:
        self.exit()

    def action_focus_search(self) -> None:
        search = self.query_one("#search", Input)
        search.display = True
        search.focus()
        self._search_enabled = True
        self._render_footer("SEARCH: type to filter, Esc to clear")

    def action_help(self) -> None:
        self._set_state("help")

    def action_catalog(self) -> None:
        self._set_state("catalog")

    def action_home(self) -> None:
        self._set_state("home")

    def action_diagnostics(self) -> None:
        self._set_state("diagnostics")

    def action_progress(self) -> None:
        self._set_state("progress")

    def action_success(self) -> None:
        self._set_state("success")

    def action_error(self) -> None:
        self._set_state("error")

    def action_quota(self) -> None:
        self._set_state("quota")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "search":
            return
        query = event.value.strip().lower()
        source = self._catalog_items() if self._state == "catalog" else self._home_items
        if not query:
            self._menu_items = list(source)
        else:
            self._menu_items = [item for item in source if query in item.label.lower()]
        self._selected_index = 0
        self._render()

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self.action_select()

    def _set_state(self, state: str) -> None:
        self._state = state
        if state == "catalog":
            self._menu_items = self._catalog_items()
            self._selected_index = 0
        elif state == "home":
            self._menu_items = list(self._home_items)
            self._selected_index = 0
        else:
            self._menu_items = []

        search = self.query_one("#search", Input)
        search.value = ""
        search.display = False
        self._search_enabled = False
        self._render()

    def _render(self) -> None:
        status = self.query_one("#status", Static)
        status.update(self._binary_leaf_chain())

        if self._state == "home":
            self._render_menu("ZERO-ARG LAUNCHER / HOME", self._menu_items)
            self._render_footer("↑/↓ navigate  Enter run  Ctrl+C quit")
            return

        if self._state == "catalog":
            self._render_menu("COMMAND CATALOG (SPECIFICATION §3)", self._menu_items)
            self._render_footer("↑/↓ navigate  Enter run  Ctrl+C quit")
            return

        templates = {
            "boot": self._boot_view(),
            "help": self._help_view(),
            "diagnostics": self._diagnostics_view(),
            "progress": self._progress_view(),
            "success": self._success_view(),
            "error": self._error_view(),
            "quota": self._quota_view(),
        }
        viewport = self.query_one("#viewport", Static)
        viewport.update(templates.get(self._state, self._help_view()))
        self._render_footer("↑/↓ navigate  Enter run  Ctrl+C quit")

    def _binary_leaf_chain(self) -> str:
        width = max(40, self.size.width - 8)
        leaves = ["010", "101", "010", "101", "010", "101"]
        cores = ["01110", "11101", "01110", "10111", "01110", "11101"]
        gap = "   "
        colors = ["#ff00ff", "#ff1493", "#ff4fd8", "#e040fb", "#c026d3"]

        top_parts: list[str] = []
        mid_parts: list[str] = []
        bottom_parts: list[str] = []

        visible_length = 0
        index = 0
        while visible_length + 5 <= width:
            color = colors[index % len(colors)]
            leaf = leaves[index % len(leaves)]
            core = cores[index % len(cores)]

            top_parts.append(f"[bold {color}] {leaf} [/]")
            mid_parts.append(f"[bold {color}]{core}[/]")
            bottom_parts.append(f"[bold {color}] {leaf} [/]")

            visible_length += 5 + len(gap)
            index += 1

        top = gap.join(top_parts)
        middle = gap.join(mid_parts)
        bottom = gap.join(bottom_parts)

        return f"{top}\n{middle}\n{bottom}"

    def _render_menu(self, title: str, items: list[MenuEntry]) -> None:
        viewport = self.query_one("#viewport", Static)
        lines = [title, ""]
        if not items:
            lines.append("  no matches")
        else:
            for index, item in enumerate(items):
                pointer = "›" if index == self._selected_index else " "
                lines.append(f" {pointer} {item.label}")
        viewport.update("\n".join(lines))

    def _render_footer(self, text: str) -> None:
        self.query_one("#footer", Static).update(text)

    def _catalog_items(self) -> list[MenuEntry]:
        entries: list[MenuEntry] = []
        for group, commands in self.all_commands.items():
            entries.append(MenuEntry(label=f"[{group}]", value="noop"))
            for display, args in commands:
                entries.append(MenuEntry(label=f"  {display}", value=f"run:{' '.join(args)}"))
        return entries

    def _catalog_value_to_command(self, value: str) -> list[str] | None:
        if not value.startswith("run:"):
            return None
        raw = value.removeprefix("run:").strip()
        if not raw:
            return None
        return raw.split()

    def _apply_mode_class(self) -> None:
        self.remove_class("mode-local")
        self.remove_class("mode-managed")
        if self.runtime_mode == "managed":
            self.add_class("mode-managed")
        else:
            self.add_class("mode-local")

    @staticmethod
    def _boot_view() -> str:
        return "\n".join(
            [
                "╭────────────────────────────── BOOT / WELCOME ──────────────────────────────╮",
                "│ MATRIOSHA MEMORY VAULT                                                        │",
                "│ Initializing trusted terminal surfaces...                                     │",
                "│ [✓] command grammar loaded     [✓] mode policy loaded    [✓] vault offline   │",
                "╰───────────────────────────────────────────────────────────────────────────────╯",
            ]
        )

    @staticmethod
    def _help_view() -> str:
        return "\n".join(
            [
                "╭──────────────────────────────── HELP ─────────────────────────────────────────╮",
                "│ Home: h   Catalog: a   Search: /   Quit: q                                     │",
                "│ Diagnostics: d   Progress: p   Success: s   Error: e   Quota: w               │",
                "│ This UI launches canonical CLI commands and preserves --json/--plain behavior. │",
                "╰───────────────────────────────────────────────────────────────────────────────╯",
            ]
        )

    @staticmethod
    def _diagnostics_view() -> str:
        return "\n".join(
            [
                "╭──────────────────────────── STATUS / DIAGNOSTICS ─────────────────────────────╮",
                "│ ✓ vault lock state        : ready                                               │",
                "│ ✓ command registry        : complete                                             │",
                "│ ℹ managed transport       : offline in local mode                               │",
                "│ ⚠ narrow terminal fallback: active when width < 90 columns                      │",
                "╰───────────────────────────────────────────────────────────────────────────────╯",
            ]
        )

    @staticmethod
    def _progress_view() -> str:
        return "\n".join(
            [
                "╭──────────────────────────── ACTIVITY / PROGRESS ───────────────────────────────╮",
                "│ Sync verification        [███████████░░░░░░░░░] 58%   29/50   00:12 elapsed     │",
                "│ Hash recomputation       [██████████████████░░░] 90%   45/50                    │",
                "╰───────────────────────────────────────────────────────────────────────────────╯",
            ]
        )

    @staticmethod
    def _success_view() -> str:
        return "\n".join(
            [
                "╭────────────────────────────── SUCCESS STATE ───────────────────────────────────╮",
                "│ ✓ MEMORY STORED                                                                 │",
                "│ id        m_01J9...9K2F                                                         │",
                "│ merkle    4a7c2d9b...ef10                                                       │",
                "│ next      matriosha memory recall m_01J9...9K2F                                 │",
                "╰───────────────────────────────────────────────────────────────────────────────╯",
            ]
        )

    @staticmethod
    def _error_view() -> str:
        return "\n".join(
            [
                "╭────────────────────────────── ERROR STATE ─────────────────────────────────────╮",
                "│ ✖ AUTH FAILED                                                                    │",
                "│ category: AUTH  code: AUTH-002  exit: 20                                         │",
                "│ fix: run `matriosha auth login`                                                  │",
                "│ debug: http_status=401 provider=supabase                                         │",
                "╰───────────────────────────────────────────────────────────────────────────────╯",
            ]
        )

    @staticmethod
    def _quota_view() -> str:
        return "\n".join(
            [
                "╭──────────────────────────── QUOTA WARNING STATE ────────────────────────────────╮",
                "│ ⚠ usage 2.4 GB / 3.0 GB (80%)                                                    │",
                "│ actions: [1] matriosha compress  [2] matriosha delete  [3] matriosha billing upgrade │",
                "╰───────────────────────────────────────────────────────────────────────────────╯",
            ]
        )
