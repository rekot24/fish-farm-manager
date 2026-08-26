"""
config_manager.py

Loads, validates, and saves all configuration.

Three config sources:
  - settings.json    : global app settings (adb path, health thresholds, private server link, etc.)
  - devices.json     : per-device configuration list
  - profiles/*.yaml  : behavior/logic profiles (read-only at runtime)

All paths are resolved relative to the project root (the folder containing main.py).
"""

from __future__ import annotations

import json
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _project_root() -> Path:
    """Returns the project root: the folder containing this file's parent (bot/)."""
    return Path(__file__).resolve().parent.parent


def _config_dir() -> Path:
    return _project_root() / "config"


def _profiles_dir() -> Path:
    return _config_dir() / "profiles"


def _settings_path() -> Path:
    return _config_dir() / "settings.json"


def _devices_path() -> Path:
    return _config_dir() / "devices.json"


# ---------------------------------------------------------------------------
# Settings dataclass
# ---------------------------------------------------------------------------

@dataclass
class HealthConfig:
    battery_min_percent: int = 20
    battery_resume_percent: int = 80
    temp_throttle_celsius: float = 45.0
    temp_pause_celsius: float = 52.0
    temp_resume_celsius: float = 40.0
    adb_reconnect_interval_s: int = 10


@dataclass
class DebugConfig:
    save_failed_captures: bool = True
    log_state_changes: bool = True
    screenshot_dir: str = "debug_shots"


@dataclass
class Settings:
    adb_path: str = "adb"
    scan_interval_ms: int = 800
    template_confidence_default: float = 0.82
    private_server_link: str = ""
    capture_backend_default: str = "scrcpy"   # "scrcpy" or "adb"
    health: HealthConfig = field(default_factory=HealthConfig)
    debug: DebugConfig = field(default_factory=DebugConfig)


# ---------------------------------------------------------------------------
# Device config dataclass
# ---------------------------------------------------------------------------

@dataclass
class DetectorConfig:
    """
    Config for one detector on one device.

    image      : path to the template image (shared or device-specific)
    click_offset: (dx, dy) pixels from detected image center to tap target.
                  [0, 0] means tap dead center of the detected image.
    """
    image: str = ""
    click_offset: List[int] = field(default_factory=lambda: [0, 0])


@dataclass
class TimerConfig:
    auto_farm_reset_interval_min: int = 15
    end_run_reset_interval_min: int = 10


@dataclass
class DeviceConfig:
    serial: str = ""
    nickname: str = ""
    model: str = ""
    enabled: bool = True
    is_lead: bool = False
    profile: str = "support_private"
    capture_backend: str = "scrcpy"           # "scrcpy" or "adb"
    scan_interval_ms: int = 800
    detectors: Dict[str, DetectorConfig] = field(default_factory=dict)
    timers: TimerConfig = field(default_factory=TimerConfig)
    eaten_by_name_image: str = ""
    device_image_overrides: List[str] = field(default_factory=list)
    notes: str = ""


# ---------------------------------------------------------------------------
# Profile dataclass (loaded from YAML, read-only at runtime)
# ---------------------------------------------------------------------------

@dataclass
class ProfileConfig:
    profile_name: str = ""
    role: str = "support"              # "lead" or "support"
    server_type: str = "private"       # "private" or "public"
    status: str = "active"            # "active" or "stub"
    behaviors: Dict[str, Any] = field(default_factory=dict)
    detectors_required: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_settings() -> Settings:
    """
    Load global settings from config/settings.json.
    Missing keys fall back to dataclass defaults — never crashes on partial config.
    """
    path = _settings_path()
    if not path.exists():
        print(f"[config] settings.json not found at {path}, using defaults")
        return Settings()

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    health_data = data.get("health", {})
    debug_data = data.get("debug", {})

    return Settings(
        adb_path=data.get("adb_path", "adb"),
        scan_interval_ms=data.get("scan_interval_ms", 800),
        template_confidence_default=data.get("template_confidence_default", 0.82),
        private_server_link=data.get("private_server_link", ""),
        capture_backend_default=data.get("capture_backend_default", "scrcpy"),
        health=HealthConfig(
            battery_min_percent=health_data.get("battery_min_percent", 20),
            battery_resume_percent=health_data.get("battery_resume_percent", 80),
            temp_throttle_celsius=health_data.get("temp_throttle_celsius", 45.0),
            temp_pause_celsius=health_data.get("temp_pause_celsius", 52.0),
            temp_resume_celsius=health_data.get("temp_resume_celsius", 40.0),
            adb_reconnect_interval_s=health_data.get("adb_reconnect_interval_s", 10),
        ),
        debug=DebugConfig(
            save_failed_captures=debug_data.get("save_failed_captures", True),
            log_state_changes=debug_data.get("log_state_changes", True),
            screenshot_dir=debug_data.get("screenshot_dir", "debug_shots"),
        ),
    )


def save_settings(settings: Settings) -> None:
    """Write settings back to config/settings.json."""
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "adb_path": settings.adb_path,
        "scan_interval_ms": settings.scan_interval_ms,
        "template_confidence_default": settings.template_confidence_default,
        "private_server_link": settings.private_server_link,
        "capture_backend_default": settings.capture_backend_default,
        "health": {
            "battery_min_percent": settings.health.battery_min_percent,
            "battery_resume_percent": settings.health.battery_resume_percent,
            "temp_throttle_celsius": settings.health.temp_throttle_celsius,
            "temp_pause_celsius": settings.health.temp_pause_celsius,
            "temp_resume_celsius": settings.health.temp_resume_celsius,
            "adb_reconnect_interval_s": settings.health.adb_reconnect_interval_s,
        },
        "debug": {
            "save_failed_captures": settings.debug.save_failed_captures,
            "log_state_changes": settings.debug.log_state_changes,
            "screenshot_dir": settings.debug.screenshot_dir,
        },
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_devices() -> List[DeviceConfig]:
    """
    Load per-device configuration from config/devices.json.
    Returns empty list if file does not exist or is empty.
    """
    path = _devices_path()
    if not path.exists():
        return []

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        print(f"[config] devices.json is not a list, returning empty")
        return []

    devices = []
    for entry in data:
        # Parse detectors dict
        detectors: Dict[str, DetectorConfig] = {}
        for det_name, det_data in entry.get("detectors", {}).items():
            detectors[det_name] = DetectorConfig(
                image=det_data.get("image", ""),
                click_offset=det_data.get("click_offset", [0, 0]),
            )

        # Parse timers
        timer_data = entry.get("timers", {})
        timers = TimerConfig(
            auto_farm_reset_interval_min=timer_data.get("auto_farm_reset_interval_min", 15),
            end_run_reset_interval_min=timer_data.get("end_run_reset_interval_min", 10),
        )

        devices.append(DeviceConfig(
            serial=entry.get("serial", ""),
            nickname=entry.get("nickname", ""),
            model=entry.get("model", ""),
            enabled=entry.get("enabled", True),
            is_lead=entry.get("is_lead", False),
            profile=entry.get("profile", "support_private"),
            capture_backend=entry.get("capture_backend", "scrcpy"),
            scan_interval_ms=entry.get("scan_interval_ms", 800),
            detectors=detectors,
            timers=timers,
            eaten_by_name_image=entry.get("eaten_by_name_image", ""),
            device_image_overrides=entry.get("device_image_overrides", []),
            notes=entry.get("notes", ""),
        ))

    return devices


def save_devices(devices: List[DeviceConfig]) -> None:
    """
    Write device list back to config/devices.json.
    Enforces the one-lead rule before saving.
    """
    # Enforce: only one lead allowed
    lead_count = sum(1 for d in devices if d.is_lead)
    if lead_count > 1:
        raise ValueError(f"Cannot save: {lead_count} devices marked as lead. Only 1 allowed.")

    path = _devices_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = []
    for dev in devices:
        detectors_data = {}
        for det_name, det_cfg in dev.detectors.items():
            detectors_data[det_name] = {
                "image": det_cfg.image,
                "click_offset": det_cfg.click_offset,
            }

        data.append({
            "serial": dev.serial,
            "nickname": dev.nickname,
            "model": dev.model,
            "enabled": dev.enabled,
            "is_lead": dev.is_lead,
            "profile": dev.profile,
            "capture_backend": dev.capture_backend,
            "scan_interval_ms": dev.scan_interval_ms,
            "detectors": detectors_data,
            "timers": {
                "auto_farm_reset_interval_min": dev.timers.auto_farm_reset_interval_min,
                "end_run_reset_interval_min": dev.timers.end_run_reset_interval_min,
            },
            "eaten_by_name_image": dev.eaten_by_name_image,
            "device_image_overrides": dev.device_image_overrides,
            "notes": dev.notes,
        })

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_profile(profile_name: str) -> ProfileConfig:
    """
    Load a behavior profile from config/profiles/{profile_name}.yaml.

    Raises FileNotFoundError if the profile does not exist.
    Stub profiles (status: stub) load successfully — the caller decides
    whether to block on stub status.
    """
    path = _profiles_dir() / f"{profile_name}.yaml"
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
    for yaml_path in _profiles_dir().glob("*.yaml"):
        name = yaml_path.stem
        try:
            profiles[name] = load_profile(name)
        except Exception as e:
            print(f"[config] Failed to load profile '{name}': {e}")
    return profiles


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_devices(devices: List[DeviceConfig]) -> List[str]:
    """
    Run basic validation on the device list.
    Returns a list of warning strings (empty = all good).
    These are warnings, not fatal errors — the UI shows them.
    """
    warnings = []
    lead_count = sum(1 for d in devices if d.is_lead)

    if lead_count == 0:
        warnings.append("No lead device configured. Private mode cascade reset and eaten-by detection will not work.")
    if lead_count > 1:
        warnings.append(f"Multiple lead devices configured ({lead_count}). Only one is allowed.")

    valid_profiles = {"lead_private", "support_private", "lead_public", "support_public"}
    for dev in devices:
        if dev.profile not in valid_profiles:
            warnings.append(f"Device '{dev.nickname or dev.serial}' has unknown profile: '{dev.profile}'")
        if dev.is_lead and "support" in dev.profile:
            warnings.append(f"Device '{dev.nickname or dev.serial}' is marked as lead but has a support profile.")
        if not dev.serial:
            warnings.append(f"Device '{dev.nickname}' has no serial number set.")

    return warnings


def validate_settings(settings: Settings) -> List[str]:
    """Basic validation on global settings. Returns warning strings."""
    warnings = []
    if not settings.private_server_link:
        warnings.append("Private server link is not set. Devices will not be able to auto-rejoin the private tank.")
    if settings.capture_backend_default not in ("scrcpy", "adb"):
        warnings.append(f"Unknown capture_backend_default: '{settings.capture_backend_default}'. Use 'scrcpy' or 'adb'.")
    return warnings
