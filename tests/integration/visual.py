from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

_ARTIFACTS_DIR = Path(__file__).resolve().parents[2] / "artifacts" / "screenshots"
_SCENARIOS_DIR = Path(__file__).resolve().parent / "visual_scenarios"


@dataclass(frozen=True)
class VisualScenario:
    file_path: Path
    name: str
    modes: tuple[str, ...]
    state: str
    command: tuple[str, ...]
    parity_critical: bool = False

    @property
    def expected_files(self) -> list[str]:
        return [f"{self.name}__{mode}__{self.state}.png" for mode in self.modes]


def load_visual_scenarios() -> list[VisualScenario]:
    scenarios: list[VisualScenario] = []
    for path in sorted(_SCENARIOS_DIR.glob("*.toml")):
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
        modes = tuple(str(mode) for mode in payload["modes"])
        scenarios.append(
            VisualScenario(
                file_path=path,
                name=str(payload["name"]),
                modes=modes,
                state=str(payload["state"]),
                command=tuple(str(part) for part in payload["command"]),
                parity_critical=bool(payload.get("parity_critical", False)),
            )
        )
    return scenarios


def sanitize_output(text: str) -> str:
    clean = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    clean = clean.replace("…", "...")
    clean = re.sub(r"[0-9a-f]{8}-[0-9a-f-]{27}", "<MEMORY_ID>", clean)
    clean = re.sub(r"[0-9a-f]{64}", "<HASH64>", clean)
    clean = re.sub(r"[0-9a-f-]{8,24}\.\.\.[0-9a-f]{6,16}", "<TRUNCATED_HEX>", clean)
    clean = re.sub(r"\d{4}-\d{2}-\d{2}T[^\s]+Z", "<TIMESTAMP>", clean)
    clean = re.sub(r"/tmp/[\w\-./]+", "<TMP_PATH>", clean)
    clean = re.sub(r"/home/[\w\-./]+", "<HOME_PATH>", clean)
    clean = re.sub(r"\b\d+\.\d{1,2}s\b", "<ELAPSED>", clean)
    clean = re.sub(r"\r", "\n", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean.strip()


def render_terminal_screenshot(text: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas = Image.new("RGB", (1280, 720), "#0d1117")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()

    header = "matriosha visual verification"
    draw.text((24, 16), header, fill="#58a6ff", font=font)

    y = 48
    for raw_line in text.splitlines():
        line = raw_line[:150]
        draw.text((24, y), line, fill="#e6edf3", font=font)
        y += 14
        if y >= 700:
            break

    canvas.save(destination)


def assert_pixel_perfect_match(actual_path: Path, baseline_path: Path) -> None:
    with Image.open(actual_path) as current, Image.open(baseline_path) as baseline:
        if current.size != baseline.size:
            raise AssertionError(f"image size mismatch: {current.size} != {baseline.size}")
        diff = ImageChops.difference(current, baseline)
        if diff.getbbox() is not None:
            raise AssertionError(f"pixel regression detected for {baseline_path.name}")


def artifacts_dir() -> Path:
    _ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    return _ARTIFACTS_DIR
