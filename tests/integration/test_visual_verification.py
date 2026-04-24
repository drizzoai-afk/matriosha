from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from tests.integration.visual import (
    artifacts_dir,
    assert_pixel_perfect_match,
    load_visual_scenarios,
    render_terminal_screenshot,
    sanitize_output,
)


def _set_mode(cli_runner, mode: str, env: dict[str, str]) -> None:
    result = cli_runner.invoke(["--json", "mode", "set", mode], env=env)
    assert result.exit_code == 0, (result.stdout or str(result.exception))


@pytest.mark.integration
@pytest.mark.parametrize("scenario", load_visual_scenarios(), ids=lambda s: s.name)
def test_visual_verification_workflow(initialized_vault, cli_runner, managed_client, managed_profile, tmp_path: Path, scenario) -> None:
    update_baseline = os.getenv("MATRIOSHA_UPDATE_VISUAL_BASELINE", "0") == "1"

    for mode in scenario.modes:
        env: dict[str, str] = {}
        if mode == "managed":
            env.update(
                {
                    "MATRIOSHA_MANAGED_ENDPOINT": managed_client.endpoint,
                    "MATRIOSHA_MANAGED_TOKEN": managed_client.token,
                }
            )
        _set_mode(cli_runner, mode, env)

        run = cli_runner.invoke(list(scenario.command), env=env)
        transcript = sanitize_output(run.stdout or "<no output>")
        screenshot_name = f"{scenario.name}__{mode}__{scenario.state}.png"

        generated_path = tmp_path / screenshot_name
        render_terminal_screenshot(transcript, generated_path)

        baseline_path = artifacts_dir() / screenshot_name
        if update_baseline:
            shutil.copyfile(generated_path, baseline_path)
            continue

        assert baseline_path.exists(), (
            f"missing baseline screenshot: {baseline_path}. "
            "Run MATRIOSHA_UPDATE_VISUAL_BASELINE=1 pytest tests/integration/test_visual_verification.py"
        )
        assert_pixel_perfect_match(generated_path, baseline_path)
