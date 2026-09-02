"""
bot/health_monitor.py

Device health monitoring: battery, temperature, ADB connection.

Called by each DeviceWorker at the top of every loop iteration.
Returns a HealthStatus that the worker uses to decide whether to
proceed, throttle, pause, or sleep.

ADB commands used:
  Battery:     adb shell dumpsys battery | grep level
  Temperature: adb shell cat /sys/class/thermal/thermal_zone*/temp
  ADB check:   adb -s {serial} get-state
"""

from __future__ import annotations

import subprocess
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from config.settings import HealthConfig


# ---------------------------------------------------------------------------
# Health status dataclass
# ---------------------------------------------------------------------------

@dataclass
class HealthStatus:
    """
    Snapshot of a device's health at one point in time.
    Exposed by each DeviceWorker for UI polling.
    """
    serial: str
    battery_percent: int = -1         # -1 = unknown
    temperature_celsius: float = -1.0 # -1 = unknown
    adb_connected: bool = True
    worker_state: str = "RUNNING"     # RUNNING, BATTERY_SLEEP, TEMP_PAUSE, ADB_LOST
    last_updated: float = field(default_factory=time.time)

    # Derived flags (set by HealthMonitor.check())
    battery_critical: bool = False    # below min threshold
    battery_low: bool = False         # below resume threshold (still charging)
    temp_throttle: bool = False       # above throttle threshold
    temp_critical: bool = False       # above pause threshold


# ---------------------------------------------------------------------------
# Health monitor
# ---------------------------------------------------------------------------

class HealthMonitor:
    """
    Checks device health via ADB and returns a HealthStatus.

    One HealthMonitor instance per DeviceWorker.
    """

    def __init__(self, serial: str, adb_path: str, cfg: HealthConfig):
        self.serial = serial
        self.adb_path = adb_path
        self.cfg = cfg

        # Cache last known values so a failed ADB call doesn't wipe good data
        self._last_battery = -1
        self._last_temp = -1.0
        self._last_adb_ok = True

    def check(self) -> HealthStatus:
        """
        Run all health checks and return a HealthStatus.
        Non-blocking — each check has its own timeout.
        """
        battery = self._get_battery()
        temp = self._get_temperature()
        adb_ok = self._check_adb()

        # Update cache
        if battery >= 0:
            self._last_battery = battery
        if temp >= 0:
            self._last_temp = temp
        self._last_adb_ok = adb_ok

        # Use cached values if current check failed
        effective_battery = battery if battery >= 0 else self._last_battery
        effective_temp = temp if temp >= 0 else self._last_temp

        status = HealthStatus(
            serial=self.serial,
            battery_percent=effective_battery,
            temperature_celsius=effective_temp,
            adb_connected=adb_ok,
            last_updated=time.time(),
        )

        # Set derived flags
        if effective_battery >= 0:
            status.battery_critical = effective_battery < self.cfg.battery_min_percent
            status.battery_low = effective_battery < self.cfg.battery_resume_percent

        if effective_temp >= 0:
            status.temp_throttle = effective_temp > self.cfg.temp_throttle_celsius
            status.temp_critical = effective_temp > self.cfg.temp_pause_celsius

        return status

    # ------------------------------------------------------------------
    # ADB polling helpers
    # ------------------------------------------------------------------

    def _adb(self, *args, timeout: float = 5.0) -> str:
        """
        Run an ADB command and return stdout as a string.
        Returns empty string on any failure.
        """
        try:
            result = subprocess.run(
                [self.adb_path, "-s", self.serial] + list(args),
                capture_output=True,
                timeout=timeout,
                text=True,
            )
            if result.returncode == 0:
                return result.stdout
            return ""
        except Exception:
            return ""

    def _check_adb(self) -> bool:
        """Verify the device is reachable via ADB."""
        try:
            result = subprocess.run(
                [self.adb_path, "-s", self.serial, "get-state"],
                capture_output=True,
                timeout=5.0,
                text=True,
            )
            return result.returncode == 0 and "device" in result.stdout
        except Exception:
            return False

    def _get_battery(self) -> int:
        """
        Read battery level from dumpsys battery.
        Returns -1 if unavailable.
        """
        output = self._adb("shell", "dumpsys", "battery")
        if not output:
            return -1

        # Look for "level: XX" in the output
        match = re.search(r"level:\s*(\d+)", output)
        if match:
            return int(match.group(1))
        return -1

    def _get_temperature(self) -> float:
        """
        Read thermal zone temperatures and return the maximum.

        Pixel devices expose temperatures in /sys/class/thermal/thermal_zone*/temp
        Values are in millidegrees Celsius (divide by 1000 for °C).

        Returns -1.0 if unavailable.
        """
        output = self._adb(
            "shell",
            "for f in /sys/class/thermal/thermal_zone*/temp; do cat $f 2>/dev/null; echo; done"
        )
        if not output:
            return -1.0

        max_temp = -1.0
        for line in output.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                raw = int(line)
                # Values can be in millidegrees (>1000) or degrees directly
                if raw > 1000:
                    temp_c = raw / 1000.0
                else:
                    temp_c = float(raw)

                # Sanity check: ignore obviously wrong values
                if 0 < temp_c < 120:
                    max_temp = max(max_temp, temp_c)
            except ValueError:
                continue

        return max_temp

    def attempt_adb_reconnect(self) -> bool:
        """
        Try to reconnect a dropped ADB connection.
        Returns True if reconnect succeeded.
        """
        try:
            result = subprocess.run(
                [self.adb_path, "reconnect", self.serial],
                capture_output=True,
                timeout=10.0,
                text=True,
            )
            time.sleep(2.0)  # give device a moment to re-enumerate
            return self._check_adb()
        except Exception:
            return False
