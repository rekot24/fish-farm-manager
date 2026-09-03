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
from config.constants import (
    DEFAULT_TEMPLATE_CONFIDENCE,
    CRASH_DETECT_AFTER_S, CRASH_RECOVERY_SETTLE_S,
    BATTERY_SLEEP_SETTLE_S, BATTERY_SLEEP_POLL_S, WAKE_SETTLE_S,
    TEMP_PAUSE_POLL_S, THERMAL_THROTTLE_MULTIPLIER,
    ADB_QUICK_TIMEOUT_S, ADB_DEFAULT_TIMEOUT_S, ADB_LAUNCH_TIMEOUT_S,
    ADB_SCREENCAP_TIMEOUT_S, ADB_SCREENCAP_BATCH_TIMEOUT_S,
    ADB_RECONNECT_SETTLE_S,
)


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

    # Device recovery/settle timing — see config/constants.py for why each
    # of these is tunable (the farm spans a Pixel 3 to a Pixel 8a).
    crash_detect_after_s: float = CRASH_DETECT_AFTER_S
    crash_recovery_settle_s: float = CRASH_RECOVERY_SETTLE_S
    battery_sleep_settle_s: float = BATTERY_SLEEP_SETTLE_S
    battery_sleep_poll_s: float = BATTERY_SLEEP_POLL_S
    wake_settle_s: float = WAKE_SETTLE_S
    temp_pause_poll_s: float = TEMP_PAUSE_POLL_S
    thermal_throttle_multiplier: float = THERMAL_THROTTLE_MULTIPLIER


@dataclass
class AdbConfig:
    """
    ADB command timeouts, by tier — see config/constants.py for why these
    are three separate values rather than one shared timeout.

    Only wired live for call sites that already hold a Settings/HealthMonitor
    reference (HealthMonitor, DeviceManager). bot/actions.py and the
    standalone Tkinter tool dialogs (image_capture_tool.py,
    coordinate_finder.py, add_device_dialog.py) use the config/constants.py
    values directly as static defaults rather than reading from here —
    threading a live Settings reference through those free functions is a
    bigger change than this phase's scope. See AUDIT.md / ROADMAP.md Phase 3.
    """
    quick_timeout_s: float = ADB_QUICK_TIMEOUT_S
    default_timeout_s: float = ADB_DEFAULT_TIMEOUT_S
    launch_timeout_s: float = ADB_LAUNCH_TIMEOUT_S
    screencap_timeout_s: float = ADB_SCREENCAP_TIMEOUT_S
    screencap_batch_timeout_s: float = ADB_SCREENCAP_BATCH_TIMEOUT_S
    reconnect_settle_s: float = ADB_RECONNECT_SETTLE_S


@dataclass
class DebugConfig:
    """
    Live "what is the app doing right now" output (Layer 3) — distinct
    from LoggingConfig above, which is the persistent on-disk record
    (Layer 7). Every category here is ADDITIVE: it supplements the
    always-on INFO/WARNING/ERROR logs from device_worker.py/device_manager.py
    with extra, opt-in diagnostic detail. It never gates or replaces an
    existing log line — turning debug off never makes something that's
    normally visible disappear.
    """
    enabled: bool = False              # master switch — off by default in production; nothing below fires while this is False
    log_state_changes: bool = True     # dump full detector results alongside the existing state-transition log line
    log_detections: bool = False       # dump every detector's found/score, every scan — verbose
    log_actions: bool = False          # trace which action-dispatch branch ran for the resolved state
    log_health: bool = False           # dump raw battery/temp/ADB-check values, every scan
    log_config_reads: bool = False     # log when settings/device configs are reloaded from the UI
    screenshot_on_event: bool = False  # also save a death screenshot in private mode (public mode already always does, as a business feature — this extends it to private mode as a debug aid)
    save_failed_captures: bool = True
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
    template_confidence_default: float = DEFAULT_TEMPLATE_CONFIDENCE
    private_server_link: str = ""
    capture_backend_default: str = "scrcpy"   # "scrcpy" or "adb"
    health: HealthConfig = field(default_factory=HealthConfig)
    adb: AdbConfig = field(default_factory=AdbConfig)
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
    adb_data = data.get("adb", {})
    debug_data = data.get("debug", {})
    logging_data = data.get("logging", {})

    return Settings(
        adb_path=data.get("adb_path", "adb"),
        scan_interval_ms=data.get("scan_interval_ms", 800),
        template_confidence_default=data.get("template_confidence_default", DEFAULT_TEMPLATE_CONFIDENCE),
        private_server_link=data.get("private_server_link", ""),
        capture_backend_default=data.get("capture_backend_default", "scrcpy"),
        health=HealthConfig(
            battery_min_percent=health_data.get("battery_min_percent", 20),
            battery_resume_percent=health_data.get("battery_resume_percent", 80),
            temp_throttle_celsius=health_data.get("temp_throttle_celsius", 45.0),
            temp_pause_celsius=health_data.get("temp_pause_celsius", 52.0),
            temp_resume_celsius=health_data.get("temp_resume_celsius", 40.0),
            adb_reconnect_interval_s=health_data.get("adb_reconnect_interval_s", 10),
            crash_detect_after_s=health_data.get("crash_detect_after_s", CRASH_DETECT_AFTER_S),
            crash_recovery_settle_s=health_data.get("crash_recovery_settle_s", CRASH_RECOVERY_SETTLE_S),
            battery_sleep_settle_s=health_data.get("battery_sleep_settle_s", BATTERY_SLEEP_SETTLE_S),
            battery_sleep_poll_s=health_data.get("battery_sleep_poll_s", BATTERY_SLEEP_POLL_S),
            wake_settle_s=health_data.get("wake_settle_s", WAKE_SETTLE_S),
            temp_pause_poll_s=health_data.get("temp_pause_poll_s", TEMP_PAUSE_POLL_S),
            thermal_throttle_multiplier=health_data.get("thermal_throttle_multiplier", THERMAL_THROTTLE_MULTIPLIER),
        ),
        adb=AdbConfig(
            quick_timeout_s=adb_data.get("quick_timeout_s", ADB_QUICK_TIMEOUT_S),
            default_timeout_s=adb_data.get("default_timeout_s", ADB_DEFAULT_TIMEOUT_S),
            launch_timeout_s=adb_data.get("launch_timeout_s", ADB_LAUNCH_TIMEOUT_S),
            screencap_timeout_s=adb_data.get("screencap_timeout_s", ADB_SCREENCAP_TIMEOUT_S),
            screencap_batch_timeout_s=adb_data.get("screencap_batch_timeout_s", ADB_SCREENCAP_BATCH_TIMEOUT_S),
            reconnect_settle_s=adb_data.get("reconnect_settle_s", ADB_RECONNECT_SETTLE_S),
        ),
        debug=DebugConfig(
            enabled=debug_data.get("enabled", False),
            log_state_changes=debug_data.get("log_state_changes", True),
            log_detections=debug_data.get("log_detections", False),
            log_actions=debug_data.get("log_actions", False),
            log_health=debug_data.get("log_health", False),
            log_config_reads=debug_data.get("log_config_reads", False),
            screenshot_on_event=debug_data.get("screenshot_on_event", False),
            save_failed_captures=debug_data.get("save_failed_captures", True),
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
            "crash_detect_after_s": settings.health.crash_detect_after_s,
            "crash_recovery_settle_s": settings.health.crash_recovery_settle_s,
            "battery_sleep_settle_s": settings.health.battery_sleep_settle_s,
            "battery_sleep_poll_s": settings.health.battery_sleep_poll_s,
            "wake_settle_s": settings.health.wake_settle_s,
            "temp_pause_poll_s": settings.health.temp_pause_poll_s,
            "thermal_throttle_multiplier": settings.health.thermal_throttle_multiplier,
        },
        "adb": {
            "quick_timeout_s": settings.adb.quick_timeout_s,
            "default_timeout_s": settings.adb.default_timeout_s,
            "launch_timeout_s": settings.adb.launch_timeout_s,
            "screencap_timeout_s": settings.adb.screencap_timeout_s,
            "screencap_batch_timeout_s": settings.adb.screencap_batch_timeout_s,
            "reconnect_settle_s": settings.adb.reconnect_settle_s,
        },
        "debug": {
            "enabled": settings.debug.enabled,
            "log_state_changes": settings.debug.log_state_changes,
            "log_detections": settings.debug.log_detections,
            "log_actions": settings.debug.log_actions,
            "log_health": settings.debug.log_health,
            "log_config_reads": settings.debug.log_config_reads,
            "screenshot_on_event": settings.debug.screenshot_on_event,
            "save_failed_captures": settings.debug.save_failed_captures,
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
