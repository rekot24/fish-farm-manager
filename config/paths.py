"""
config/paths.py

Shared path resolution for every config file the app reads or writes.
All paths are resolved relative to the project root (the folder containing
main.py), regardless of the process's current working directory.

Split out on its own so config/settings.py, config/devices.py,
config/profiles.py, and config/presets.py don't each need their own copy
of the same handful of one-line functions.

Testing note: each of those modules does `from config.paths import
X_path`, which binds its own copy of the function at import time.
Monkeypatching `config.paths.X_path` in a test does NOT affect that
already-bound copy — patch the name on the *consuming* module instead
(e.g. `config.devices.devices_path`), or the test silently hits the real
file. This bit twice in this project's own history (see CLAUDE.md, Phase 6
and Phase 3/7) before the pattern was fixed everywhere.
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


def behavior_presets_path() -> Path:
    return config_dir() / "behavior_presets.json"
