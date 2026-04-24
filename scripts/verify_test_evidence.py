from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_DIR = REPO_ROOT / "tests" / "integration" / "visual_scenarios"
SCREENSHOTS_DIR = REPO_ROOT / "artifacts" / "screenshots"
MANIFEST_PATH = REPO_ROOT / "docs" / "TEST_EVIDENCE.md"

_REQUIRED_CHECKLIST_LINES = (
    "- [x] Deterministic screenshot captured for every visual scenario file",
    "- [x] Parity-critical flows include both local and managed screenshots",
    "- [x] Pixel-perfect visual regression tests are enabled in CI",
)


def _load_expected_screenshots() -> tuple[list[str], list[str]]:
    expected: list[str] = []
    parity_errors: list[str] = []

    for scenario_file in sorted(SCENARIOS_DIR.glob("*.toml")):
        payload = tomllib.loads(scenario_file.read_text(encoding="utf-8"))
        name = str(payload["name"])
        state = str(payload["state"])
        modes = [str(mode) for mode in payload["modes"]]

        if payload.get("parity_critical") and sorted(modes) != ["local", "managed"]:
            parity_errors.append(
                f"{scenario_file.name}: parity_critical requires modes ['local', 'managed'], got {modes}"
            )

        for mode in modes:
            expected.append(f"{name}__{mode}__{state}.png")

    return expected, parity_errors


def _manifest_referenced_files(markdown: str) -> set[str]:
    matches = re.findall(r"artifacts/screenshots/([\w.-]+\.png)", markdown)
    return set(matches)


def main() -> int:
    errors: list[str] = []

    if not SCENARIOS_DIR.exists():
        errors.append(f"missing scenario directory: {SCENARIOS_DIR}")
    if not MANIFEST_PATH.exists():
        errors.append(f"missing manifest: {MANIFEST_PATH}")

    if errors:
        for error in errors:
            print(f"[evidence-gate] {error}")
        return 1

    expected_files, parity_errors = _load_expected_screenshots()
    errors.extend(parity_errors)

    manifest = MANIFEST_PATH.read_text(encoding="utf-8")
    referenced = _manifest_referenced_files(manifest)

    for checklist_line in _REQUIRED_CHECKLIST_LINES:
        if checklist_line not in manifest:
            errors.append(f"manifest missing checklist sign-off: {checklist_line}")

    for screenshot in expected_files:
        screenshot_path = SCREENSHOTS_DIR / screenshot
        if not screenshot_path.exists():
            errors.append(f"missing screenshot artifact: {screenshot_path}")
        if screenshot not in referenced:
            errors.append(f"manifest missing screenshot reference: artifacts/screenshots/{screenshot}")

    if errors:
        for error in errors:
            print(f"[evidence-gate] {error}")
        return 1

    print(f"[evidence-gate] OK: validated {len(expected_files)} screenshots and manifest coverage")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
