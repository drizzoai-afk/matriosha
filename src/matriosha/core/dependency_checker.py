"""Read-only dependency inspection helpers for `matriosha init` (P6.9)."""

from __future__ import annotations

import ctypes.util
import importlib.metadata
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_MIN_PYTHON = (3, 11)
_SYSTEM_PACKAGES = ("tesseract-ocr", "poppler-utils", "libmagic1")


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _requirements_path() -> Path:
    return _project_root() / "requirements.txt"


def _parse_requirement_names(requirements_path: Path) -> list[str]:
    if not requirements_path.exists():
        return []

    parsed: list[str] = []
    for raw_line in requirements_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("-r", "--requirement", "-e", "--editable")):
            continue

        # Keep only the package token before version markers/extras/environment markers.
        token = re.split(r"[<>=!~; ]", line, maxsplit=1)[0].strip()
        token = token.split("[", maxsplit=1)[0].strip()
        if token:
            parsed.append(token)

    # Preserve order while de-duplicating.
    deduped: list[str] = []
    seen: set[str] = set()
    for name in parsed:
        key = name.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(name)
    return deduped


def check_python_version() -> dict[str, object]:
    """Return Python runtime compatibility details."""

    major, minor, patch = sys.version_info[:3]
    compatible = (major, minor) >= _MIN_PYTHON
    return {
        "required": ".".join(str(part) for part in _MIN_PYTHON),
        "current": f"{major}.{minor}.{patch}",
        "compatible": compatible,
        "reason": None if compatible else f"requires >= {_MIN_PYTHON[0]}.{_MIN_PYTHON[1]}",
    }


def detect_os_type() -> dict[str, object]:
    """Detect host OS, package-manager hints, and support status."""

    system = platform.system().lower()
    machine = platform.machine().lower()
    info: dict[str, object] = {
        "os": system,
        "machine": machine,
        "version": platform.version(),
        "distribution": None,
        "distribution_version": None,
        "package_manager": None,
        "supported": False,
        "reason": "unsupported platform",
    }

    if system == "linux":
        os_release_path = Path("/etc/os-release")
        release_data: dict[str, str] = {}
        if os_release_path.exists():
            for raw_line in os_release_path.read_text(encoding="utf-8").splitlines():
                if "=" not in raw_line:
                    continue
                key, value = raw_line.split("=", maxsplit=1)
                release_data[key.strip()] = value.strip().strip('"')

        distro = release_data.get("ID", "linux").lower()
        version_id = release_data.get("VERSION_ID", "")
        info["distribution"] = distro
        info["distribution_version"] = version_id or None

        if distro in {"ubuntu", "debian"}:
            info["package_manager"] = "apt"
            min_version = 20.04 if distro == "ubuntu" else 10.0
            try:
                current_version = float(version_id)
            except (TypeError, ValueError):
                current_version = 0.0
            supported = current_version >= min_version
            info["supported"] = supported
            info["reason"] = (
                None if supported else f"{distro} {version_id} is below minimum {min_version}"
            )
            return info

        info["reason"] = f"linux distribution '{distro}' not supported (requires Ubuntu/Debian)"
        return info

    if system == "darwin":
        info["os"] = "macos"
        info["package_manager"] = "brew" if shutil.which("brew") else None
        version_str = platform.mac_ver()[0]
        info["version"] = version_str or info["version"]
        try:
            major = int((version_str or "0").split(".", maxsplit=1)[0])
        except ValueError:
            major = 0
        supported = major >= 11
        info["supported"] = supported
        if not supported:
            info["reason"] = f"macOS {version_str or 'unknown'} is below minimum 11"
        elif info["package_manager"] is None:
            info["reason"] = "Homebrew not found"
        else:
            info["reason"] = None
        return info

    return info


def check_sudo_available() -> dict[str, object]:
    """Check whether passwordless sudo is currently available."""

    if platform.system().lower() != "linux":
        return {
            "available": False,
            "checked": False,
            "reason": "sudo check is only relevant on Linux",
        }

    sudo_path = shutil.which("sudo")
    if not sudo_path:
        return {"available": False, "checked": False, "reason": "sudo command not found"}

    try:
        result = subprocess.run(
            [sudo_path, "-n", "true"], check=False, capture_output=True, timeout=3
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "available": False,
            "checked": True,
            "reason": f"sudo probe failed: {exc.__class__.__name__}",
        }

    if result.returncode == 0:
        return {"available": True, "checked": True, "reason": None}

    return {
        "available": False,
        "checked": True,
        "reason": "sudo requires interactive password or is not permitted",
    }


def check_system_packages() -> dict[str, object]:
    """Detect required system-level runtime packages/tools."""

    checks = {
        "tesseract-ocr": {
            "detected": shutil.which("tesseract") is not None,
            "probe": "which tesseract",
        },
        "poppler-utils": {
            "detected": any(shutil.which(tool) for tool in ("pdfinfo", "pdftotext", "pdftoppm")),
            "probe": "which pdfinfo|pdftotext|pdftoppm",
        },
        "libmagic1": {
            "detected": ctypes.util.find_library("magic") is not None
            or shutil.which("file") is not None,
            "probe": "ctypes.util.find_library('magic') or which file",
        },
    }

    missing = [name for name, payload in checks.items() if not payload["detected"]]
    return {
        "required": list(_SYSTEM_PACKAGES),
        "packages": checks,
        "missing": missing,
        "all_present": len(missing) == 0,
    }


def check_python_packages(requirements_path: Path | None = None) -> dict[str, object]:
    """Validate that requirements from requirements.txt are importable as installed dists."""

    path = requirements_path or _requirements_path()
    requirement_names = _parse_requirement_names(path)

    packages: dict[str, dict[str, object]] = {}
    missing: list[str] = []

    for package_name in requirement_names:
        normalized = package_name.replace("_", "-").lower()
        try:
            version = importlib.metadata.version(normalized)
            packages[package_name] = {"installed": True, "version": version}
        except importlib.metadata.PackageNotFoundError:
            packages[package_name] = {"installed": False, "version": None}
            missing.append(package_name)

    return {
        "requirements_file": str(path),
        "required_count": len(requirement_names),
        "packages": packages,
        "missing": missing,
        "all_present": len(missing) == 0,
    }


def get_system_report(requirements_path: Path | None = None) -> dict[str, object]:
    """Aggregate init bootstrap checks into a single deterministic report."""

    os_info = detect_os_type()
    python_info = check_python_version()
    system_packages = check_system_packages()
    python_packages = check_python_packages(requirements_path=requirements_path)
    sudo_info = check_sudo_available()

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "os": os_info,
        "python": python_info,
        "sudo": sudo_info,
        "system_packages": system_packages,
        "python_packages": python_packages,
        "summary": {
            "ready": bool(
                os_info.get("supported")
                and python_info.get("compatible")
                and system_packages.get("all_present")
                and python_packages.get("all_present")
            ),
            "missing_system_packages": system_packages.get("missing", []),
            "missing_python_packages": python_packages.get("missing", []),
        },
    }
