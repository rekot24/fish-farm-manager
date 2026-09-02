"""
config/settings.py

Global app settings: adb path, health thresholds, private server link,
debug flags, and persistent-logging config.

Loads from and saves to config/settings.json. Split out of the former
bot/config_manager.py (which also handled devices.json and profiles/*.yaml)
so this file has one job.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List

from config.paths import settings_path


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
class LoggingConfig:
    """
    Persistent logging (Layer 7) — distinct from DebugConfig above, which is
    for live "what is the app doing right now" output. This controls the
    durable on-disk record: logs/app.log (rotating) and logs/errors.log
    (errors and criticals only, always written regardless of these settings —
    see bot/app_logger.py for why).
    """
    enabled: bool = True
    level: str = "INFO"        # minimum level written to app.log / console: DEBUG, INFO, WARNING, ERROR, CRITICAL
    log_to_file: bool = True
    log_to_console: bool = True
    max_file_size_mb: int = 10
    backup_count: int = 3      # how many rotated app.log files to keep


@dataclass
class Settings:
    adb_path: str = "adb"
    scan_interval_ms: int = 800
    template_confidence_default: float = 0.82
    private_server_link: str = ""
    capture_backend_default: str = "scrcpy"   # "scrcpy" or "adb"
    health: HealthConfig = field(default_factory=HealthConfig)
    debug: DebugConfig = field(default_factory=DebugConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def load_settings() -> Settings:
    """
    Load global settings from config/settings.json.
    Missing keys fall back to dataclass defaults — never crashes on partial config.
    """
    path = settings_path()
    if not path.exists():
        print(f"[config] settings.json not found at {path}, using defaults")
        return Settings()

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    health_data = data.get("health", {})
    debug_data = data.get("debug", {})
    logging_data = data.get("logging", {})

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
        logging=LoggingConfig(
            enabled=logging_data.get("enabled", True),
            level=logging_data.get("level", "INFO"),
            log_to_file=logging_data.get("log_to_file", True),
            log_to_console=logging_data.get("log_to_console", True),
            max_file_size_mb=logging_data.get("max_file_size_mb", 10),
            backup_count=logging_data.get("backup_count", 3),
        ),
    )


def save_settings(settings: Settings) -> None:
    """Write settings back to config/settings.json."""
    path = settings_path()
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
        "logging": {
            "enabled": settings.logging.enabled,
            "level": settings.logging.level,
            "log_to_file": settings.logging.log_to_file,
            "log_to_console": settings.logging.log_to_console,
            "max_file_size_mb": settings.logging.max_file_size_mb,
            "backup_count": settings.logging.backup_count,
        },
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_settings(settings: Settings) -> List[str]:
    """Basic validation on global settings. Returns warning strings."""
    warnings = []
    if not settings.private_server_link:
        warnings.append("Private server link is not set. Devices will not be able to auto-rejoin the private tank.")
    if settings.capture_backend_default not in ("scrcpy", "adb"):
        warnings.append(f"Unknown capture_backend_default: '{settings.capture_backend_default}'. Use 'scrcpy' or 'adb'.")
    return warnings
