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
from config.constants import CASCADE_RESET_DELAY_S
from bot import app_logger


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

    # Cascade reset: after a lead device's end-run fires, it broadcasts a
    # signal telling support devices to end-run too, after a delay. Only
    # ever consulted when DeviceConfig.is_lead is True. Moved here from
    # profile YAML's cascade_reset_on_end_run block (Phase 6 — see AUDIT.md)
    # since it's the same "reset cycle" concept as the two settings above,
    # and the code that reads it already lives in device_worker.py's
    # "Timer logic" section, not its death-handling code.
    cascade_reset_enabled: bool = True
    cascade_reset_delay_after_lead_s: float = CASCADE_RESET_DELAY_S


@dataclass
class DeathBehaviorConfig:
    """
    What a device does when it dies. Moved from profile YAML's dead_state /
    eaten_by_detection blocks (Phase 6 — see AUDIT.md / ROADMAP.md) so these
    are live per-device settings, re-read every cycle, instead of loaded
    once from a profile at worker start.

    eaten_by_detection_* only ever apply to the lead device (device_worker.py
    only checks them when DeviceConfig.is_lead is True) — kept per-device
    rather than global since a farm could plausibly want a different lead
    at different times, each with their own eaten-by behavior.
    disable_auto_on_death / save_screenshot_on_death / revive_enabled only
    apply in public mode (device_worker._handle_dead_public).
    """
    disable_auto_on_death: bool = True
    save_screenshot_on_death: bool = True
    revive_enabled: bool = False
    eaten_by_detection_enabled: bool = False
    eaten_by_detection_trigger_support_end_run: bool = False


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
    death_behavior: DeathBehaviorConfig = field(default_factory=DeathBehaviorConfig)
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
        app_logger.log("[config] devices.json is not a list, returning empty", "ERROR")
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

        # is_lead/profile are needed below to compute migration-safe defaults
        # for the fields Phase 6 moved off profile YAML — an entry saved
        # before this phase won't have them, and the fallback here
        # reproduces exactly what the old profile-derived value was for
        # that role, so existing devices don't change behavior on upgrade.
        is_lead = entry.get("is_lead", False)
        profile_str = entry.get("profile", "support_private")

        # Parse timers — supports both old format (no enabled flags) and new
        timer_data = entry.get("timers", {})
        timers = TimerConfig(
            auto_farm_reset_enabled=timer_data.get("auto_farm_reset_enabled", True),
            auto_farm_reset_interval_min=timer_data.get("auto_farm_reset_interval_min", 15),
            end_run_reset_enabled=timer_data.get("end_run_reset_enabled", True),
            end_run_reset_interval_min=timer_data.get("end_run_reset_interval_min", 10),
            # Every profile's cascade_reset_on_end_run either matched these
            # values or omitted the block entirely — in which case the old
            # code's own inline default (cascade_cfg.get(..., True/30)) was
            # already effectively True/30.0 for every device.
            cascade_reset_enabled=timer_data.get("cascade_reset_enabled", True),
            cascade_reset_delay_after_lead_s=timer_data.get(
                "cascade_reset_delay_after_lead_s", CASCADE_RESET_DELAY_S
            ),
        )

        # Parse death behavior — defaults replicate what each role's profile
        # YAML used to set (see config/profiles/*.yaml history / AUDIT.md §2).
        death_data = entry.get("death_behavior", {})
        death_behavior = DeathBehaviorConfig(
            disable_auto_on_death=death_data.get("disable_auto_on_death", True),
            save_screenshot_on_death=death_data.get("save_screenshot_on_death", True),
            revive_enabled=death_data.get("revive_enabled", is_lead),
            eaten_by_detection_enabled=death_data.get("eaten_by_detection_enabled", is_lead),
            eaten_by_detection_trigger_support_end_run=death_data.get(
                "eaten_by_detection_trigger_support_end_run", "private" in profile_str
            ),
        )

        devices.append(DeviceConfig(
            serial=entry.get("serial", ""),
            nickname=entry.get("nickname", ""),
            model=entry.get("model", ""),
            enabled=entry.get("enabled", True),
            is_lead=is_lead,
            profile=profile_str,
            capture_backend=entry.get("capture_backend", "scrcpy"),
            scan_interval_ms=entry.get("scan_interval_ms", 800),
            detectors=detectors,
            timers=timers,
            death_behavior=death_behavior,
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
                "cascade_reset_enabled": dev.timers.cascade_reset_enabled,
                "cascade_reset_delay_after_lead_s": dev.timers.cascade_reset_delay_after_lead_s,
            },
            "death_behavior": {
                "disable_auto_on_death": dev.death_behavior.disable_auto_on_death,
                "save_screenshot_on_death": dev.death_behavior.save_screenshot_on_death,
                "revive_enabled": dev.death_behavior.revive_enabled,
                "eaten_by_detection_enabled": dev.death_behavior.eaten_by_detection_enabled,
                "eaten_by_detection_trigger_support_end_run": dev.death_behavior.eaten_by_detection_trigger_support_end_run,
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
