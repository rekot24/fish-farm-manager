"""
config/presets.py

BehaviorPreset — a named snapshot of a device's TimerConfig,
DeathBehaviorConfig, HealthResponseConfig, and disabled_detectors —
save-able and restorable onto any device.

This is the standard's actual "Profile" concept (dev-standards
app-framework.md, Layer 2: "a named snapshot of all feature flag states...
save current flags -> profile, load profile -> restores flags"). It is
deliberately NOT called "profile" in this codebase, because that word was
already taken by config/profiles.py's ProfileConfig — state-detection rule
sets, a different and valid concept that just happens to share the word.
CLAUDE.md's very first session log anticipated this exact naming collision
before the split was even identified. See AUDIT.md / ROADMAP.md Phase 8.

Scope — what's in a snapshot: every field Phase 3/6/11 established as a
live, per-cycle-checked "feature flag" — TimerConfig, DeathBehaviorConfig,
HealthResponseConfig, disabled_detectors. Phase 8 shipped this scoped to
just the first two; Phase 11 expanded it to match once there was more
toggleable behavior to snapshot — a preset covering only half a device's
behavior would be a confusing half-measure. Deliberately still excluded:
DeviceConfig.role (device identity, not a behavior toggle — traced every
role-gated decision in the bot loop before Phase 8 excluded it; role lives
entirely in the code that reads it, never in anything a preset touches, so
excluding it can't strip role-based logic), profile/capture_backend/
scan_interval_ms/enabled (identity or capture tuning, not behavior).
disabled_detectors is detector *names*, which can legitimately differ
between profiles (e.g. "revive_button" only exists on public profiles) —
applying a preset with a name the target's profile doesn't use is harmless,
the name simply never matches anything in that profile's detectors_required.

Loads from and saves to config/behavior_presets.json. Unlike
config/profiles.py's YAML rule sets (hand-edited only), this is meant to be
managed through the UI — ROADMAP Phase 11 owns the actual Save-as/Load
buttons; this module is the data layer they'll call into. No presets are
seeded by default.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Dict, List

from config.paths import behavior_presets_path
from config.devices import DeviceConfig, TimerConfig, DeathBehaviorConfig, HealthResponseConfig
from bot import app_logger


# ---------------------------------------------------------------------------
# Preset dataclass
# ---------------------------------------------------------------------------

@dataclass
class BehaviorPreset:
    name: str = ""
    timers: TimerConfig = field(default_factory=TimerConfig)
    death_behavior: DeathBehaviorConfig = field(default_factory=DeathBehaviorConfig)
    health_response: HealthResponseConfig = field(default_factory=HealthResponseConfig)
    disabled_detectors: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def load_all_presets() -> Dict[str, BehaviorPreset]:
    """
    Load every saved preset from config/behavior_presets.json.
    Returns an empty dict if the file doesn't exist or is empty — there are
    no presets shipped by default.
    """
    path = behavior_presets_path()
    if not path.exists():
        return {}

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        app_logger.log("[config] behavior_presets.json is not an object, returning empty", "ERROR")
        return {}

    presets: Dict[str, BehaviorPreset] = {}
    for name, entry in data.items():
        try:
            presets[name] = _preset_from_dict(name, entry)
        except Exception as e:
            app_logger.log(f"[config] Failed to load preset '{name}': {e}", "ERROR")
    return presets


def load_preset(name: str) -> BehaviorPreset:
    """
    Load one preset by name.

    Raises KeyError if no preset with that name exists.
    """
    presets = load_all_presets()
    if name not in presets:
        raise KeyError(f"No behavior preset named '{name}'")
    return presets[name]


def save_preset(name: str, device_cfg: DeviceConfig) -> BehaviorPreset:
    """
    Snapshot device_cfg's behavior fields (timers, death_behavior,
    health_response, disabled_detectors) under `name` and persist it to
    config/behavior_presets.json. Overwrites any existing preset with the
    same name.

    Returns the saved BehaviorPreset.
    """
    preset = BehaviorPreset(
        name=name,
        timers=replace(device_cfg.timers),
        death_behavior=replace(device_cfg.death_behavior),
        health_response=replace(device_cfg.health_response),
        disabled_detectors=list(device_cfg.disabled_detectors),
    )
    presets = load_all_presets()
    presets[name] = preset
    _write_all(presets)
    return preset


def delete_preset(name: str) -> bool:
    """Remove a preset by name. Returns True if it existed and was removed."""
    presets = load_all_presets()
    if name not in presets:
        return False
    del presets[name]
    _write_all(presets)
    return True


def list_preset_names() -> List[str]:
    """Names of every saved preset, for populating a UI dropdown/list."""
    return sorted(load_all_presets().keys())


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def apply_preset(device_cfg: DeviceConfig, preset: BehaviorPreset) -> DeviceConfig:
    """
    Return a new DeviceConfig with device_cfg's behavior fields (timers,
    death_behavior, health_response, disabled_detectors) replaced by the
    preset's — every other field (serial, nickname, role, profile, ...)
    passes through unchanged.

    Does not mutate device_cfg or save anything; the caller decides whether
    and how to persist the result (e.g. via config.devices.save_devices()).
    """
    return replace(
        device_cfg,
        timers=replace(preset.timers),
        death_behavior=replace(preset.death_behavior),
        health_response=replace(preset.health_response),
        disabled_detectors=list(preset.disabled_detectors),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _preset_from_dict(name: str, entry: dict) -> BehaviorPreset:
    """Build a BehaviorPreset from one config/behavior_presets.json entry, defaulting missing fields."""
    timer_data = entry.get("timers", {})
    timers = TimerConfig(
        auto_farm_reset_enabled=timer_data.get("auto_farm_reset_enabled", True),
        auto_farm_reset_interval_min=timer_data.get("auto_farm_reset_interval_min", 15),
        end_run_reset_enabled=timer_data.get("end_run_reset_enabled", True),
        end_run_reset_interval_min=timer_data.get("end_run_reset_interval_min", 10),
        cascade_reset_enabled=timer_data.get("cascade_reset_enabled", True),
        cascade_reset_delay_after_lead_s=timer_data.get("cascade_reset_delay_after_lead_s", 30.0),
    )

    death_data = entry.get("death_behavior", {})
    death_behavior = DeathBehaviorConfig(
        disable_auto_on_death=death_data.get("disable_auto_on_death", True),
        save_screenshot_on_death=death_data.get("save_screenshot_on_death", True),
        revive_enabled=death_data.get("revive_enabled", False),
        eaten_by_detection_enabled=death_data.get("eaten_by_detection_enabled", False),
        eaten_by_detection_trigger_support_end_run=death_data.get(
            "eaten_by_detection_trigger_support_end_run", False
        ),
    )

    health_response_data = entry.get("health_response", {})
    health_response = HealthResponseConfig(
        battery_protection_enabled=health_response_data.get("battery_protection_enabled", True),
        temp_protection_enabled=health_response_data.get("temp_protection_enabled", True),
    )

    disabled_detectors = entry.get("disabled_detectors", [])

    return BehaviorPreset(
        name=name, timers=timers, death_behavior=death_behavior,
        health_response=health_response, disabled_detectors=disabled_detectors,
    )


def _write_all(presets: Dict[str, BehaviorPreset]) -> None:
    """Write the full preset dict back to config/behavior_presets.json."""
    path = behavior_presets_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {}
    for name, preset in presets.items():
        data[name] = {
            "timers": {
                "auto_farm_reset_enabled": preset.timers.auto_farm_reset_enabled,
                "auto_farm_reset_interval_min": preset.timers.auto_farm_reset_interval_min,
                "end_run_reset_enabled": preset.timers.end_run_reset_enabled,
                "end_run_reset_interval_min": preset.timers.end_run_reset_interval_min,
                "cascade_reset_enabled": preset.timers.cascade_reset_enabled,
                "cascade_reset_delay_after_lead_s": preset.timers.cascade_reset_delay_after_lead_s,
            },
            "death_behavior": {
                "disable_auto_on_death": preset.death_behavior.disable_auto_on_death,
                "save_screenshot_on_death": preset.death_behavior.save_screenshot_on_death,
                "revive_enabled": preset.death_behavior.revive_enabled,
                "eaten_by_detection_enabled": preset.death_behavior.eaten_by_detection_enabled,
                "eaten_by_detection_trigger_support_end_run":
                    preset.death_behavior.eaten_by_detection_trigger_support_end_run,
            },
            "health_response": {
                "battery_protection_enabled": preset.health_response.battery_protection_enabled,
                "temp_protection_enabled": preset.health_response.temp_protection_enabled,
            },
            "disabled_detectors": preset.disabled_detectors,
        }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
