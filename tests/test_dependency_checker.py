from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import matriosha.core.dependency_checker as checker


def test_check_python_version_has_expected_shape() -> None:
    payload = cast(dict[str, Any], checker.check_python_version())

    assert set(payload.keys()) == {"required", "current", "compatible", "reason"}
    assert isinstance(payload["compatible"], bool)
    assert isinstance(payload["current"], str)


def test_detect_os_type_darwin_without_brew(monkeypatch) -> None:
    monkeypatch.setattr(checker.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(checker.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(checker.platform, "mac_ver", lambda: ("14.4.1", ("", "", ""), ""))
    monkeypatch.setattr(checker.shutil, "which", lambda _cmd: None)

    payload = cast(dict[str, Any], checker.detect_os_type())

    assert payload["os"] == "macos"
    assert payload["supported"] is True
    assert payload["package_manager"] is None
    assert payload["reason"] == "Homebrew not found"


def test_check_python_packages_parses_requirements_file(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "\n".join(
            [
                "# comment",
                "typer[all]>=0.12,<1.0",
                "rich>=13",
                "-r other.txt",
            ]
        ),
        encoding="utf-8",
    )

    payload = cast(dict[str, Any], checker.check_python_packages(requirements))

    assert payload["required_count"] == 2
    assert set(payload["packages"].keys()) == {"typer", "rich"}


def test_get_system_report_aggregates_sections(monkeypatch) -> None:
    monkeypatch.setattr(checker, "detect_os_type", lambda: {"supported": True})
    monkeypatch.setattr(checker, "check_python_version", lambda: {"compatible": True})
    monkeypatch.setattr(
        checker,
        "check_system_packages",
        lambda: {"all_present": True, "missing": []},
    )
    monkeypatch.setattr(
        checker,
        "check_python_packages",
        lambda requirements_path=None: {"all_present": True, "missing": []},
    )
    monkeypatch.setattr(checker, "check_sudo_available", lambda: {"available": True})

    payload = cast(dict[str, Any], checker.get_system_report())

    assert payload["summary"]["ready"] is True
    assert payload["summary"]["missing_system_packages"] == []
    assert payload["summary"]["missing_python_packages"] == []
