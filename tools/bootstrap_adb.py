"""Download Android Platform Tools into this repository.

This removes the requirement for ADB to be installed system-wide. On Windows:

    python tools/bootstrap_adb.py

The official Google Platform Tools archive is downloaded and extracted to:
    vendor/android/platform-tools/

The application automatically prefers that copy of ADB.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEST_ROOT = PROJECT_ROOT / "vendor" / "android"
PLATFORM_TOOLS_DIR = DEST_ROOT / "platform-tools"

DOWNLOADS = {
    "win32": "https://dl.google.com/android/repository/platform-tools-latest-windows.zip",
    "darwin": "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip",
    "linux": "https://dl.google.com/android/repository/platform-tools-latest-linux.zip",
}


def _platform_key() -> str:
    if sys.platform.startswith("win"):
        return "win32"
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("linux"):
        return "linux"
    raise RuntimeError(f"Unsupported platform for automatic ADB bootstrap: {sys.platform}")


def main() -> int:
    key = _platform_key()
    url = DOWNLOADS[key]
    adb_name = "adb.exe" if os.name == "nt" else "adb"
    expected_adb = PLATFORM_TOOLS_DIR / adb_name

    if expected_adb.exists():
        print(f"Bundled ADB is already installed: {expected_adb}")
        return 0

    DEST_ROOT.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="befish-adb-") as temp_dir:
        archive = Path(temp_dir) / "platform-tools.zip"
        print("Downloading Android Platform Tools from Google...")
        urllib.request.urlretrieve(url, archive)

        extract_dir = Path(temp_dir) / "extract"
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(extract_dir)

        extracted = extract_dir / "platform-tools"
        if not extracted.exists():
            raise RuntimeError("Downloaded archive did not contain platform-tools/")

        if PLATFORM_TOOLS_DIR.exists():
            shutil.rmtree(PLATFORM_TOOLS_DIR)
        shutil.copytree(extracted, PLATFORM_TOOLS_DIR)

    if not expected_adb.exists():
        raise RuntimeError(f"ADB was not found after extraction: {expected_adb}")

    if os.name != "nt":
        expected_adb.chmod(expected_adb.stat().st_mode | 0o111)

    print(f"Bundled ADB installed successfully: {expected_adb}")
    print("No system PATH configuration is required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
