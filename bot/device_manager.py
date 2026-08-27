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
from pathlib import Path
from typing import Dict, List, Optional

from bot.config_manager import DeviceConfig, Settings, load_profile
from bot.device_worker import DeviceWorker
from bot.farm_event_bus import FarmEventBus
from detection.template_bank import TemplateBank


class DeviceManager:
    """Manages the lifecycle of all device workers."""

    def __init__(self, settings: Settings, device_cfgs: List[DeviceConfig], log_fn=None):
        self.settings = settings
        self.device_cfgs = device_cfgs
        self._log_fn = log_fn or print

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
        for serial, worker in list(self._workers.items()):
            self._log(f"[DeviceManager] Stopping worker for {serial}")
            worker.stop()
            self.event_bus.unregister(serial)
        self._workers.clear()

    def start_device(self, serial: str) -> bool:
        dev_cfg = self._find_cfg(serial)
        if not dev_cfg:
            self._log(f"[DeviceManager] No config found for serial: {serial}")
            return False
        if not dev_cfg.enabled:
            self._log(f"[DeviceManager] Device is disabled: {dev_cfg.nickname or serial}")
            return False
        return self._start_worker(dev_cfg)

    def stop_device(self, serial: str) -> None:
        worker = self._workers.pop(serial, None)
        if worker:
            worker.stop()
        self.event_bus.unregister(serial)

    def _start_worker(self, dev_cfg: DeviceConfig) -> bool:
        existing = self._workers.get(dev_cfg.serial)
        if existing:
            if existing.is_running():
                self._log(f"[DeviceManager] Worker already running for {dev_cfg.serial}")
                return False
            # A worker whose thread exited (for example, capture connect failure)
            # must not block a later restart attempt.
            self._workers.pop(dev_cfg.serial, None)
            self.event_bus.unregister(dev_cfg.serial)
            self._log(f"[DeviceManager] Removed stale worker for {dev_cfg.serial}")

        try:
            profile_cfg = load_profile(dev_cfg.profile)
        except FileNotFoundError as e:
            self._log(f"[DeviceManager] Profile not found for {dev_cfg.nickname}: {e}")
            return False

        if profile_cfg.status == "stub":
            self._log(
                f"[DeviceManager] Profile '{dev_cfg.profile}' is a stub (Phase 1). "
                f"Skipping {dev_cfg.nickname or dev_cfg.serial}."
            )
            return False

        self.event_bus.register(dev_cfg.serial)

        worker = DeviceWorker(
            device_cfg=dev_cfg,
            profile_cfg=profile_cfg,
            settings=self.settings,
            event_bus=self.event_bus,
            template_bank=self.template_bank,
            all_device_cfgs=self.device_cfgs,
            log_fn=self._log_fn,
        )
        self._workers[dev_cfg.serial] = worker
        worker.start()
        self._log(f"[DeviceManager] Worker started: {dev_cfg.nickname or dev_cfg.serial}")
        return True

    # ------------------------------------------------------------------
    # Status polling (called by UI)
    # ------------------------------------------------------------------

    def get_all_statuses(self) -> List[dict]:
        statuses = []
        for dev_cfg in self.device_cfgs:
            worker = self._workers.get(dev_cfg.serial)
            running = bool(worker and worker.is_running())

            if running:
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
                })
        return statuses

    def get_timer_info(self, serial: str) -> Optional[dict]:
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
            "end_run_remaining_s": end_remaining,
        }

    # ------------------------------------------------------------------
    # Config reload (called after GUI saves changes)
    # ------------------------------------------------------------------

    def reload_device_configs(self, new_cfgs: List[DeviceConfig]) -> None:
        old_cfgs = {cfg.serial: cfg for cfg in self.device_cfgs}
        self.device_cfgs = new_cfgs

        for worker in self._workers.values():
            worker.all_devices = new_cfgs

        for cfg in new_cfgs:
            worker = self._workers.get(cfg.serial)
            if not worker:
                continue

            old_cfg = old_cfgs.get(cfg.serial)
            restart_required = bool(
                old_cfg
                and (
                    old_cfg.capture_backend != cfg.capture_backend
                    or old_cfg.profile != cfg.profile
                )
            )

            if restart_required:
                self._log(
                    f"[DeviceManager] Restarting {cfg.nickname or cfg.serial} "
                    "to apply profile/capture backend changes"
                )
                self.stop_device(cfg.serial)
                if cfg.enabled:
                    self._start_worker(cfg)
                continue

            worker.cfg = cfg

    def reload_settings(self, new_settings: Settings) -> None:
        adb_path_changed = self.settings.adb_path != new_settings.adb_path
        running_serials = [
            serial for serial, worker in self._workers.items()
            if worker.is_running()
        ]

        self.settings = new_settings

        if adb_path_changed and running_serials:
            self._log("[DeviceManager] ADB path changed; restarting running workers")
            for serial in running_serials:
                self.stop_device(serial)
            for serial in running_serials:
                cfg = self._find_cfg(serial)
                if cfg and cfg.enabled:
                    self._start_worker(cfg)
            return

        for worker in self._workers.values():
            worker.settings = new_settings
            worker._health_monitor.adb_path = new_settings.adb_path
            worker._health_monitor.cfg = new_settings.health

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
