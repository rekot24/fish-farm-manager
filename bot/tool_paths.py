"""Project-local external tool path resolution.

The farm should run from a fresh clone without requiring ADB to be installed
system-wide. Resolution order for ADB is:

1. An explicit configured path, if it exists.
2. The repo-local Android Platform Tools installation under vendor/android.
3. ADB found on the system PATH.
4. The repo-local expected path (so error messages point to the bootstrap target).

A configured value of "adb", "auto", or an empty string means automatic
resolution rather than a hard dependency on the system PATH.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def bundled_adb_path() -> Path:
    exe = "adb.exe" if os.name == "nt" else "adb"
    return project_root() / "vendor" / "android" / "platform-tools" / exe


def resolve_adb_path(configured_path: str | None = None) -> str:
    configured = (configured_path or "").strip()

    # Preserve a genuinely explicit path when it exists. Relative paths are
    # resolved from the repository root so they remain clone-location agnostic.
    if configured and configured.lower() not in {"adb", "auto"}:
        candidate = Path(configured).expanduser()
        if not candidate.is_absolute():
            candidate = project_root() / candidate
        if candidate.exists():
            return str(candidate.resolve())

    local = bundled_adb_path()
    if local.exists():
        return str(local.resolve())

    system_adb = shutil.which("adb")
    if system_adb:
        return system_adb

    # Return the intended local location. Subprocess will produce a useful
    # failure, and validation can tell the user to run the bootstrap script.
    return str(local.resolve())


def is_bundled_adb(path: str | None) -> bool:
    if not path:
        return False
    try:
        return Path(path).resolve() == bundled_adb_path().resolve()
    except OSError:
        return False
