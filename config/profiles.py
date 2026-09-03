"""
config/profiles.py

Behavior/logic profiles — role- and server-type-specific rule sets
(lead_private, support_private, lead_public, support_public).

Loads from config/profiles/*.yaml. Read-only at runtime: unlike settings.py
and devices.py, there is no save_profile() — these are edited by hand, not
through the UI. Split out of the former bot/config_manager.py (which also
handled settings.json and devices.json) so this file has one job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import yaml

from config.paths import profiles_dir
from bot import app_logger


# ---------------------------------------------------------------------------
# Profile dataclass
# ---------------------------------------------------------------------------

@dataclass
class ProfileConfig:
    profile_name: str = ""
    role: str = "support"              # "lead" or "support"
    server_type: str = "private"       # "private" or "public"
    status: str = "active"             # "active" or "stub"
    behaviors: Dict[str, Any] = field(default_factory=dict)
    detectors_required: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_profile(profile_name: str) -> ProfileConfig:
    """
    Load a behavior profile from config/profiles/{profile_name}.yaml.

    Raises FileNotFoundError if the profile does not exist.
    """
    path = profiles_dir() / f"{profile_name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Profile not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return ProfileConfig(
        profile_name=data.get("profile_name", profile_name),
        role=data.get("role", "support"),
        server_type=data.get("server_type", "private"),
        status=data.get("status", "active"),
        behaviors=data.get("behaviors", {}),
        detectors_required=data.get("detectors_required", []),
    )


def load_all_profiles() -> Dict[str, ProfileConfig]:
    """Load all profiles from the profiles directory. Returns name -> ProfileConfig."""
    profiles = {}
    for yaml_path in profiles_dir().glob("*.yaml"):
        name = yaml_path.stem
        try:
            profiles[name] = load_profile(name)
        except Exception as e:
            app_logger.log(f"[config] Failed to load profile '{name}': {e}", "ERROR")
    return profiles
