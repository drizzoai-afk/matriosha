"""Safe dependency installation helpers for `matriosha init` (P6.9)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from matriosha.core.dependency_checker import check_python_packages

_INSTALL_TIMEOUT_SECONDS = 300
_ALLOWED_SYSTEM_PACKAGES = {"tesseract-ocr", "poppler-utils", "libmagic1"}


def _setup_log_path() -> Path:
    root = Path.home() / ".matriosha"
    root.mkdir(parents=True, exist_ok=True)
    return root / "setup.log"


def _log_attempt(event: str, payload: dict[str, object]) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "payload": payload,
    }
    log_path = _setup_log_path()
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def _allowed_python_packages() -> set[str]:
    report = cast(dict[str, Any], check_python_packages())
    packages = cast(dict[str, Any], report.get("packages", {}))
    return {name.lower() for name in packages.keys()}


def _run_command(command: list[str]) -> dict[str, object]:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=_INSTALL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "command": command,
            "returncode": None,
            "stdout": "",
            "stderr": f"timed out after {_INSTALL_TIMEOUT_SECONDS} seconds",
            "timeout": True,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "success": False,
            "command": command,
            "returncode": None,
            "stdout": "",
            "stderr": f"execution error: {exc.__class__.__name__}: {exc}",
            "timeout": False,
        }

    return {
        "success": result.returncode == 0,
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "timeout": False,
    }


def _map_system_package_name(package_name: str, os_type: dict[str, object]) -> str:
    package_manager = str(os_type.get("package_manager") or "")
    if package_manager == "brew":
        mapping = {
            "tesseract-ocr": "tesseract",
            "poppler-utils": "poppler",
            "libmagic1": "libmagic",
        }
        return mapping.get(package_name, package_name)
    return package_name


def install_system_package(package_name: str, os_type: dict[str, object]) -> dict[str, object]:
    """Install one allowlisted system dependency using supported package managers."""

    if package_name not in _ALLOWED_SYSTEM_PACKAGES:
        payload = {
            "success": False,
            "package": package_name,
            "error": "package not in allowlist",
            "allowlist": sorted(_ALLOWED_SYSTEM_PACKAGES),
        }
        _log_attempt("install_system_package.blocked", payload)
        return payload

    package_manager = str(os_type.get("package_manager") or "")
    mapped_name = _map_system_package_name(package_name, os_type)

    if package_manager == "apt":
        sudo_path = shutil.which("sudo")
        if sudo_path:
            command = [sudo_path, "-n", "apt-get", "install", "-y", mapped_name]
        else:
            command = ["apt-get", "install", "-y", mapped_name]
    elif package_manager == "brew":
        command = ["brew", "install", mapped_name]
    else:
        payload = {
            "success": False,
            "package": package_name,
            "error": f"unsupported package manager: {package_manager or 'unknown'}",
        }
        _log_attempt("install_system_package.unsupported", payload)
        return payload

    result = _run_command(command)
    payload = {
        "success": bool(result["success"]),
        "package": package_name,
        "mapped_package": mapped_name,
        "package_manager": package_manager,
        "timeout_seconds": _INSTALL_TIMEOUT_SECONDS,
        "command": command,
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "timeout": result["timeout"],
    }
    _log_attempt("install_system_package", payload)
    return payload


def install_python_packages(package_list: list[str]) -> dict[str, object]:
    """Install allowlisted Python dependencies via pip."""

    if not package_list:
        payload = {"success": True, "installed": [], "skipped": [], "errors": []}
        _log_attempt("install_python_packages", payload)
        return payload

    allowed = _allowed_python_packages()
    installed: list[str] = []
    skipped: list[dict[str, str]] = []
    errors: list[dict[str, object]] = []

    for package_name in package_list:
        normalized = package_name.lower()
        if normalized not in allowed:
            skipped.append({"package": package_name, "reason": "package not in allowlist"})
            continue

        command = [sys.executable, "-m", "pip", "install", package_name]
        result = _run_command(command)
        if result["success"]:
            installed.append(package_name)
        else:
            errors.append(
                {
                    "package": package_name,
                    "returncode": result["returncode"],
                    "stderr": result["stderr"],
                    "timeout": result["timeout"],
                }
            )

    success = not errors and not skipped
    payload = {
        "success": success,
        "installed": installed,
        "skipped": skipped,
        "errors": errors,
        "timeout_seconds": _INSTALL_TIMEOUT_SECONDS,
    }
    _log_attempt("install_python_packages", payload)
    return payload


def verify_installation(package_name: str, package_type: str) -> dict[str, object]:
    """Verify that a dependency is installed after attempted setup."""

    from matriosha.core.dependency_checker import check_python_packages, check_system_packages

    if package_type == "system":
        system_report = cast(dict[str, Any], check_system_packages())
        system_packages = cast(dict[str, Any], system_report.get("packages", {}))
        package_info = system_packages.get(package_name)
        detected = bool(package_info and package_info.get("detected"))
        payload = {
            "package": package_name,
            "package_type": package_type,
            "verified": detected,
            "detail": package_info,
        }
        _log_attempt("verify_installation", payload)
        return payload

    if package_type == "python":
        python_report = cast(dict[str, Any], check_python_packages())
        python_packages = cast(dict[str, Any], python_report.get("packages", {}))
        package_info = python_packages.get(package_name)
        installed = bool(package_info and package_info.get("installed"))
        payload = {
            "package": package_name,
            "package_type": package_type,
            "verified": installed,
            "detail": package_info,
        }
        _log_attempt("verify_installation", payload)
        return payload

    payload = {
        "package": package_name,
        "package_type": package_type,
        "verified": False,
        "detail": "unknown package_type (expected 'system' or 'python')",
    }
    _log_attempt("verify_installation", payload)
    return payload


def generate_manual_instructions(
    package_name: str, os_type: dict[str, object]
) -> dict[str, object]:
    """Generate user-facing fallback installation guidance."""

    os_name = str(os_type.get("os") or "unknown")
    package_manager = str(os_type.get("package_manager") or "unknown")

    if package_manager == "apt":
        command = f"sudo apt-get update && sudo apt-get install -y {package_name}"
    elif package_manager == "brew":
        mapped = _map_system_package_name(package_name, os_type)
        command = f"brew install {mapped}"
    else:
        command = f"Install '{package_name}' using your OS package manager and ensure it is available on PATH."

    payload: dict[str, object] = {
        "package": package_name,
        "os": os_name,
        "package_manager": package_manager,
        "instructions": command,
    }
    _log_attempt("generate_manual_instructions", payload)
    return payload
