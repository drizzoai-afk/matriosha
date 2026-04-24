from __future__ import annotations

from pathlib import Path

import matriosha.core.dependency_installer as installer


def test_install_system_package_rejects_non_allowlisted(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    payload = installer.install_system_package("curl", {"package_manager": "apt"})

    assert payload["success"] is False
    assert payload["error"] == "package not in allowlist"


def test_install_python_packages_allowlist_and_failures(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(installer, "_allowed_python_packages", lambda: {"rich", "typer"})

    def _fake_run(command: list[str]) -> dict[str, object]:
        if command[-1] == "rich":
            return {
                "success": True,
                "command": command,
                "returncode": 0,
                "stdout": "ok",
                "stderr": "",
                "timeout": False,
            }
        return {
            "success": False,
            "command": command,
            "returncode": 1,
            "stdout": "",
            "stderr": "boom",
            "timeout": False,
        }

    monkeypatch.setattr(installer, "_run_command", _fake_run)

    payload = installer.install_python_packages(["rich", "missing", "typer"])

    assert payload["success"] is False
    assert payload["installed"] == ["rich"]
    assert payload["skipped"] == [{"package": "missing", "reason": "package not in allowlist"}]
    assert payload["errors"][0]["package"] == "typer"


def test_verify_installation_unknown_type(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    payload = installer.verify_installation("x", "other")

    assert payload["verified"] is False
    assert "unknown package_type" in str(payload["detail"])


def test_generate_manual_instructions_for_apt(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    payload = installer.generate_manual_instructions(
        "tesseract-ocr",
        {"os": "linux", "package_manager": "apt"},
    )

    assert "apt-get install -y tesseract-ocr" in payload["instructions"]
