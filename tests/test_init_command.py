from __future__ import annotations

import json

from typer.testing import CliRunner

from cli.main import app
import cli.commands.init as init_cmd

runner = CliRunner()


def _base_report(*, missing_system: list[str], missing_python: list[str]) -> dict[str, object]:
    return {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "os": {"supported": True, "package_manager": "apt", "os": "linux"},
        "python": {"compatible": True, "current": "3.11.8", "required": "3.11"},
        "summary": {
            "ready": not missing_system and not missing_python,
            "missing_system_packages": missing_system,
            "missing_python_packages": missing_python,
        },
    }


def test_init_json_happy_path_no_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(init_cmd, "get_system_report", lambda: _base_report(missing_system=[], missing_python=[]))

    result = runner.invoke(app, ["init", "--json", "--yes"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    report_path = tmp_path / ".matriosha" / "init_report.md"
    assert report_path.exists()


def test_init_requires_yes_in_non_tty_when_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        init_cmd,
        "get_system_report",
        lambda: _base_report(missing_system=["tesseract-ocr"], missing_python=[]),
    )
    monkeypatch.setattr(init_cmd, "_is_interactive", lambda: False)

    result = runner.invoke(app, ["init", "--json"])

    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["code"] == "SYS-INIT-NONTTY"


def test_init_auto_approve_runs_install_flow(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    calls: dict[str, list[str]] = {"system": [], "python": []}

    def _system_report() -> dict[str, object]:
        # called twice: pre-check and final check
        if not calls["system"] and not calls["python"]:
            return _base_report(missing_system=["tesseract-ocr"], missing_python=["rich"])
        return _base_report(missing_system=[], missing_python=[])

    monkeypatch.setattr(init_cmd, "get_system_report", _system_report)

    def _install_system(package_name: str, os_type: dict[str, object]) -> dict[str, object]:
        calls["system"].append(package_name)
        return {"success": True}

    def _install_python(package_list: list[str]) -> dict[str, object]:
        calls["python"].extend(package_list)
        return {"success": True, "installed": package_list, "skipped": [], "errors": []}

    monkeypatch.setattr(init_cmd, "install_system_package", _install_system)
    monkeypatch.setattr(init_cmd, "install_python_packages", _install_python)
    monkeypatch.setattr(init_cmd, "verify_installation", lambda package_name, package_type: {"verified": True})

    result = runner.invoke(app, ["init", "--json", "--yes"])

    assert result.exit_code == 0
    assert calls["system"] == ["tesseract-ocr"]
    assert calls["python"] == ["rich"]


def test_init_handles_ctrl_c(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(init_cmd, "get_system_report", lambda: (_ for _ in ()).throw(KeyboardInterrupt()))

    result = runner.invoke(app, ["init", "--json", "--yes"])

    assert result.exit_code == 130
    payload = json.loads(result.stdout)
    assert payload["status"] == "interrupted"
