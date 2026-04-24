from __future__ import annotations

import asyncio
from pathlib import Path

from matriosha.cli.tui.launcher import ALL_COMMANDS, MAIN_MENU, _command_map
from matriosha.cli.tui.textual_app import MatrioshaTextualLauncher

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "artifacts" / "screenshots" / "tui"


async def _capture(
    *,
    filename: str,
    state: str,
    mode: str = "local",
    size: tuple[int, int] = (140, 42),
) -> Path:
    app = MatrioshaTextualLauncher(
        command_map=_command_map(),
        all_commands=ALL_COMMANDS,
        menu_items=MAIN_MENU,
        profile_name="default",
        runtime_mode=mode,
        initial_state=state,
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    destination = OUTPUT_DIR / filename

    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        app.save_screenshot(str(destination))

    return destination


async def main() -> None:
    plan = [
        ("zero_arg_launcher_home.png", "home", "local", (140, 42)),
        ("command_catalog_all_commands.png", "catalog", "local", (140, 42)),
        ("local_mode_state.png", "home", "local", (140, 42)),
        ("managed_mode_state.png", "home", "managed", (140, 42)),
        ("boot_welcome.png", "boot", "local", (140, 42)),
        ("status_diagnostics.png", "diagnostics", "local", (140, 42)),
        ("activity_progress.png", "progress", "managed", (140, 42)),
        ("success_state.png", "success", "local", (140, 42)),
        ("error_state.png", "error", "managed", (140, 42)),
        ("quota_warning_state.png", "quota", "managed", (140, 42)),
        ("narrow_terminal_fallback.png", "home", "local", (72, 32)),
    ]

    for filename, state, mode, size in plan:
        path = await _capture(filename=filename, state=state, mode=mode, size=size)
        print(path)


if __name__ == "__main__":
    asyncio.run(main())
