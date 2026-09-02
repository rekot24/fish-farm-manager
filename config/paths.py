"""
config/paths.py

Shared path resolution for every config file the app reads or writes.
All paths are resolved relative to the project root (the folder containing
main.py), regardless of the process's current working directory.

Split out on its own so config/settings.py, config/devices.py, and
config/profiles.py don't each need their own copy of the same five
one-line functions.
"""

from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    """Returns the project root: the folder containing main.py."""
    return Path(__file__).resolve().parent.parent


def config_dir() -> Path:
    return project_root() / "config"


def profiles_dir() -> Path:
    return config_dir() / "profiles"


def settings_path() -> Path:
    return config_dir() / "settings.json"


def devices_path() -> Path:
    return config_dir() / "devices.json"
