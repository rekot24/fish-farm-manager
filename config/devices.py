"""
config/devices.py

Per-device configuration: which devices exist, their role/profile, their
detector image overrides, and their timer settings.

Loads from and saves to config/devices.json. Split out of the former
bot/config_manager.py (which also handled settings.json and profiles/*.yaml)
so this file has one job.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List

from config.paths import devices_path


# ---------------------------------------------------------------------------
# Device config dataclass
# ---------------------------------------------------------------------------

@dataclass
class DetectorConfig:
    """
    Config for one detector on one device.

    image       : path to the template image (shared or device-specific)
    click_offset: (dx, dy) pixels from detected image center to tap target.
                  [0, 0] means tap dead center of the detected image.
    """
    image: str = ""
    click_offset: List[int] = field(default_factory=lambda: [0, 0])


@dataclass
class TimerConfig:
    # Auto-farm reset: double-taps the auto button to reset the server kick timer
    auto_farm_reset_enabled: bool = True
    auto_farm_reset_interval_min: int = 15

    # End-run reset: clicks the end-run button on a timer to keep fish size small
    end_run_reset_enabled: bool = True
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
    # Public mode revive counter.
    # Loaded from devices.json as the configured starting maximum.
    # The worker decrements it at runtime and never writes it back —
    # it resets to this value on every app restart.
    revive_count: int = 0
    notes: str = ""


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def load_devices() -> List[DeviceConfig]:
    """
    Load per-device configuration from config/devices.json.
    Returns empty list if file does not exist or is empty.
    """
    path = devices_path()
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

        # Parse timers — supports both old format (no enabled flags) and new
        timer_data = entry.get("timers", {})
        timers = TimerConfig(
            auto_farm_reset_enabled=timer_data.get("auto_farm_reset_enabled", True),
            auto_farm_reset_interval_min=timer_data.get("auto_farm_reset_interval_min", 15),
            end_run_reset_enabled=timer_data.get("end_run_reset_enabled", True),
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
            revive_count=entry.get("revive_count", 0),
            notes=entry.get("notes", ""),
        ))

    return devices


def save_devices(devices: List[DeviceConfig]) -> None:
    """
    Write device list back to config/devices.json.
    Enforces the one-lead rule before saving.
    Note: revive_count is saved as the configured starting maximum.
    The live session count is never written back.
    """
    lead_count = sum(1 for d in devices if d.is_lead)
    if lead_count > 1:
        raise ValueError(f"Cannot save: {lead_count} devices marked as lead. Only 1 allowed.")

    path = devices_path()
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
                "auto_farm_reset_enabled": dev.timers.auto_farm_reset_enabled,
                "auto_farm_reset_interval_min": dev.timers.auto_farm_reset_interval_min,
                "end_run_reset_enabled": dev.timers.end_run_reset_enabled,
                "end_run_reset_interval_min": dev.timers.end_run_reset_interval_min,
            },
            "eaten_by_name_image": dev.eaten_by_name_image,
            "device_image_overrides": dev.device_image_overrides,
            "revive_count": dev.revive_count,
            "notes": dev.notes,
        })

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_devices(devices: List[DeviceConfig]) -> List[str]:
    """
    Run basic validation on the device list.
    Returns a list of warning strings (empty = all good).
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
