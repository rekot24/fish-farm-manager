"""
bot/device_manager.py

DeviceManager — discovers ADB-connected devices and manages DeviceWorkers.

Responsibilities:
  - Parse connected ADB devices on startup and on refresh
  - Match ADB serials to saved DeviceConfig entries
  - Spawn DeviceWorker per enabled, configured device
  - Hold references to all workers for UI polling
  - Own the shared FarmEventBus and TemplateBank
"""

from __future__ import annotations

import subprocess
import re
from pathlib import Path
from typing import Dict, List, Optional

from bot.config_manager import (
    DeviceConfig, Settings, load_profile,
)
from bot.device_worker import DeviceWorker
from bot.farm_event_bus import FarmEventBus
from detection.template_bank import TemplateBank


class DeviceManager:
    """
    Manages the lifecycle of all device workers.
    One instance lives for the duration of the app.
    """

    def __init__(self, settings: Settings, device_cfgs: List[DeviceConfig], log_fn=None):
        self.settings = settings
        self.device_cfgs = device_cfgs
        self._log_fn = log_fn or print

        # Shared resources passed to all workers
        self.event_bus = FarmEventBus()
        self.template_bank = TemplateBank(
            project_root=Path(__file__).resolve().parent.parent
        )

        # serial -> DeviceWorker
        self._workers: Dict[str, DeviceWorker] = {}

    # ------------------------------------------------------------------
    # ADB device discovery
    # ------------------------------------------------------------------

    def discover_adb_devices(self) -> List[str]:
        """
        Run 'adb devices' and return a list of connected device serials.
        Filters out unauthorized and offline devices.
        """
        try:
            result = subprocess.run(
                [self.settings.adb_path, "devices"],
                capture_output=True,
                timeout=10.0,
                text=True,
            )
            serials = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line or line.startswith("List of"):
                    continue
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "device":
                    serials.append(parts[0])
            return serials
        except Exception as e:
            self._log(f"[DeviceManager] adb devices failed: {e}")
            return []

    # ------------------------------------------------------------------
    # Worker lifecycle
    # ------------------------------------------------------------------

    def start_all(self) -> None:
        """
        Start workers for all enabled, configured, and ADB-connected devices.
        Skips devices not in ADB, not enabled, or missing a profile.
        """
        connected_serials = set(self.discover_adb_devices())
        self._log(f"[DeviceManager] ADB-connected: {connected_serials}")

        for dev_cfg in self.device_cfgs:
            if not dev_cfg.enabled:
                self._log(f"[DeviceManager] Skipping disabled device: {dev_cfg.nickname or dev_cfg.serial}")
                continue

            if dev_cfg.serial not in connected_serials:
                self._log(f"[DeviceManager] Device not connected via ADB: {dev_cfg.nickname or dev_cfg.serial}")
                continue

            self._start_worker(dev_cfg)

    def stop_all(self) -> None:
        """Stop all running workers and clean up the event bus."""
        for serial, worker in list(self._workers.items()):
            self._log(f"[DeviceManager] Stopping worker for {serial}")
            worker.stop()
            self.event_bus.unregister(serial)
        self._workers.clear()

    def start_device(self, serial: str) -> bool:
        """Start a single device worker by serial. Returns True if started."""
        dev_cfg = self._find_cfg(serial)
        if not dev_cfg:
            self._log(f"[DeviceManager] No config found for serial: {serial}")
            return False
        return self._start_worker(dev_cfg)

    def stop_device(self, serial: str) -> None:
        """Stop a single device worker by serial and clean up the event bus."""
        worker = self._workers.pop(serial, None)
        if worker:
            worker.stop()
            self.event_bus.unregister(serial)

    def _start_worker(self, dev_cfg: DeviceConfig) -> bool:
        """Internal: load profile, register with event bus, start worker."""

        # F-04 fix: check if thread is actually alive, not just if the object exists.
        # A worker whose thread exited early (e.g. capture failure) stays in _workers
        # but is_running() returns False — prune it so we can restart cleanly.
        existing = self._workers.get(dev_cfg.serial)
        if existing is not None:
            if existing.is_running():
                self._log(f"[DeviceManager] Worker already running for {dev_cfg.serial}")
                return False
            else:
                # Stale worker — clean it up before spawning a new one
                self._log(f"[DeviceManager] Pruning stale worker for {dev_cfg.serial}")
                existing.stop()
                self.event_bus.unregister(dev_cfg.serial)
                del self._workers[dev_cfg.serial]

        # Load the profile
        try:
            profile_cfg = load_profile(dev_cfg.profile)
        except FileNotFoundError as e:
            self._log(f"[DeviceManager] Profile not found for {dev_cfg.nickname}: {e}")
            return False

        if profile_cfg.status == "stub":
            self._log(
                f"[DeviceManager] Profile '{dev_cfg.profile}' is a stub. "
                f"Skipping {dev_cfg.nickname or dev_cfg.serial}."
            )
            return False

        # Register fresh queue with event bus
        self.event_bus.register(dev_cfg.serial)

        # Create and start worker
        worker = DeviceWorker(
            device_cfg=dev_cfg,
            profile_cfg=profile_cfg,
            settings=self.settings,
            event_bus=self.event_bus,
            template_bank=self.template_bank,
            all_device_cfgs=self.device_cfgs,
            log_fn=self._log_fn,
        )
        worker.start()
        self._workers[dev_cfg.serial] = worker
        self._log(f"[DeviceManager] Worker started: {dev_cfg.nickname or dev_cfg.serial}")
        return True

    # ------------------------------------------------------------------
    # Status polling (called by UI)
    # ------------------------------------------------------------------

    def get_all_statuses(self) -> List[dict]:
        """
        Return a list of status dicts for UI display.
        One entry per configured device (running or not).
        """
        statuses = []
        for dev_cfg in self.device_cfgs:
            worker = self._workers.get(dev_cfg.serial)
            # Use is_running() rather than presence in dict — F-04 fix
            if worker and worker.is_running():
                health = worker.get_health()
                statuses.append({
                    "serial": dev_cfg.serial,
                    "nickname": dev_cfg.nickname,
                    "is_lead": dev_cfg.is_lead,
                    "profile": dev_cfg.profile,
                    "running": True,
                    "state": worker.current_state,
                    "battery": health.battery_percent,
                    "temp": health.temperature_celsius,
                    "worker_state": health.worker_state,
                    "adb_connected": health.adb_connected,
                    "revives_remaining": worker.revives_remaining,
                })
            else:
                statuses.append({
                    "serial": dev_cfg.serial,
                    "nickname": dev_cfg.nickname,
                    "is_lead": dev_cfg.is_lead,
                    "profile": dev_cfg.profile,
                    "running": False,
                    "state": "STOPPED",
                    "battery": -1,
                    "temp": -1.0,
                    "worker_state": "STOPPED",
                    "adb_connected": False,
                    "revives_remaining": dev_cfg.revive_count,
                })
        return statuses

    def is_device_running(self, serial: str) -> bool:
        """Return True if a worker exists for this serial and its thread is alive."""
        worker = self._workers.get(serial)
        return worker is not None and worker.is_running()

    def trigger_end_run(self, serial: str) -> bool:
        """
        Manually request an end-run on a running device (UI 'End Run' button).

        Delegates to the worker's public request_manual_end_run() rather than
        letting callers reach into worker internals. Returns True if a running
        worker was found and the request was made, False otherwise.
        """
        worker = self._workers.get(serial)
        if not worker or not worker.is_running():
            return False
        worker.request_manual_end_run()
        return True

    def get_timer_info(self, serial: str) -> Optional[dict]:
        """Return timer countdown info for a device (for UI display)."""
        worker = self._workers.get(serial)
        if not worker or not worker.is_running():
            return None

        import time
        auto_interval = worker.cfg.timers.auto_farm_reset_interval_min * 60
        end_interval = worker.cfg.timers.end_run_reset_interval_min * 60

        auto_remaining = max(0, auto_interval - (time.time() - worker._last_auto_reset))
        end_remaining = max(0, end_interval - (time.time() - worker._last_end_run_reset))

        return {
            "auto_reset_remaining_s": auto_remaining,
            "auto_reset_enabled": worker.cfg.timers.auto_farm_reset_enabled,
            "end_run_remaining_s": end_remaining,
            "end_run_enabled": worker.cfg.timers.end_run_reset_enabled,
        }

    # ------------------------------------------------------------------
    # Config reload (called after GUI saves changes)
    # ------------------------------------------------------------------

    def reload_device_configs(self, new_cfgs: List[DeviceConfig]) -> None:
        """
        Update device configs at runtime (after the GUI saves changes).
        Workers pick up timer/config changes on their next loop iteration.
        """
        self.device_cfgs = new_cfgs
        for cfg in new_cfgs:
            worker = self._workers.get(cfg.serial)
            if worker:
                worker.cfg = cfg

    def reload_settings(self, new_settings: Settings) -> None:
        """Update global settings at runtime."""
        self.settings = new_settings
        for worker in self._workers.values():
            worker.settings = new_settings

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_cfg(self, serial: str) -> Optional[DeviceConfig]:
        for cfg in self.device_cfgs:
            if cfg.serial == serial:
                return cfg
        return None

    def _log(self, msg: str) -> None:
        self._log_fn(msg)
