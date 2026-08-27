"""
bot/device_worker.py

DeviceWorker — one thread per physical device.

Each worker runs an independent loop:
  1. Health check (battery, temp, ADB)
  2. Poll FarmEventBus for incoming signals
  3. Capture frame
  4. Run detectors
  5. Resolve state
  6. Dispatch actions (timers, state-based clicks)
  7. Sleep until next scan

Workers never touch Tkinter. UI reads HealthStatus via polling.
Inter-device communication goes through FarmEventBus only.
"""

from __future__ import annotations

import threading
import time
from typing import List, Optional

from bot.config_manager import DeviceConfig, Settings, ProfileConfig
from bot.states import (
    STATE_IN_RUN, STATE_DEAD, STATE_LOBBY,
    STATE_CRASHED, STATE_UNKNOWN,
    STATE_BATTERY_SLEEP, STATE_TEMP_PAUSE, STATE_ADB_LOST,
)
from bot.state_machine import resolve_state
from bot.farm_event_bus import FarmEventBus, EVENT_CASCADE_RESET, EVENT_FORCE_END_RUN
from bot.health_monitor import HealthMonitor, HealthStatus
from bot import actions
from capture import make_backend
from capture.base import CaptureBackend
from detection.detector import run_all_detectors, find_by_path
from detection.template_bank import TemplateBank


class DeviceWorker:
    """Manages one device's bot loop in a background thread."""

    def __init__(
        self,
        device_cfg: DeviceConfig,
        profile_cfg: ProfileConfig,
        settings: Settings,
        event_bus: FarmEventBus,
        template_bank: TemplateBank,
        all_device_cfgs: List[DeviceConfig],
        log_fn=None,
    ):
        self.cfg = device_cfg
        self.profile = profile_cfg
        self.settings = settings
        self.event_bus = event_bus
        self.bank = template_bank
        self.all_devices = all_device_cfgs

        self._log_fn = log_fn or print
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self.health: HealthStatus = HealthStatus(serial=device_cfg.serial)
        self._health_lock = threading.Lock()

        self._backend: Optional[CaptureBackend] = None
        self._health_monitor = HealthMonitor(
            serial=device_cfg.serial,
            adb_path=settings.adb_path,
            cfg=settings.health,
        )

        self._last_auto_reset = time.time()
        self._last_end_run_reset = time.time()
        self._pending_cascade_reset: Optional[float] = None
        self._last_results: dict = {}

        self._unknown_since: Optional[float] = None
        self._max_unknown_s = 60.0

        self.viewer_pid: Optional[int] = None
        self.current_state: str = STATE_UNKNOWN

    # ------------------------------------------------------------------
    # Public thread control
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name=f"worker-{self.cfg.serial[:8]}",
        )
        self._thread.start()
        self._log(f"Worker started for {self.cfg.nickname or self.cfg.serial}")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        if self._backend:
            self._backend.disconnect()
        self._log(f"Worker stopped for {self.cfg.nickname or self.cfg.serial}")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def get_health(self) -> HealthStatus:
        with self._health_lock:
            return self.health

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        self._backend = make_backend(
            serial=self.cfg.serial,
            backend_type=self.cfg.capture_backend,
            adb_path=self.settings.adb_path,
        )
        if not self._backend.connect():
            self._log(f"[{self._name()}] Capture backend failed to connect. Worker exiting.")
            return

        try:
            while not self._stop_event.is_set():
                t0 = time.time()

                try:
                    self._loop_iteration()
                except Exception as e:
                    self._log(f"[{self._name()}] Unhandled error in loop: {type(e).__name__}: {e}")

                elapsed = time.time() - t0
                target_s = self.cfg.scan_interval_ms / 1000.0
                with self._health_lock:
                    if self.health.temp_throttle and not self.health.temp_critical:
                        target_s *= 2.0
                sleep_s = max(0.05, target_s - elapsed)
                self._stop_event.wait(timeout=sleep_s)
        finally:
            if self._backend:
                self._backend.disconnect()

    def _loop_iteration(self) -> None:
        health = self._health_monitor.check()
        with self._health_lock:
            self.health = health

        if not health.adb_connected:
            self._set_state(STATE_ADB_LOST)
            self._log(f"[{self._name()}] ADB disconnected, attempting reconnect...")
            if not self._health_monitor.attempt_adb_reconnect():
                return

        if health.battery_critical:
            self._enter_battery_sleep()
            return

        if health.temp_critical:
            self._enter_temp_pause()
            return

        self._handle_events()

        frame = self._backend.get_frame()
        if frame is None:
            self._log(f"[{self._name()}] Frame capture returned None, skipping iteration")
            return

        results = run_all_detectors(
            detector_names=self.profile.detectors_required,
            frame_bgr=frame,
            device_serial=self.cfg.serial,
            device_overrides=self.cfg.device_image_overrides,
            bank=self.bank,
            threshold=self.settings.template_confidence_default,
        )
        self._last_results = results

        state = resolve_state(results, self.profile.profile_name)
        previous_state = self.current_state
        self._set_state(state)

        if self.settings.debug.log_state_changes and state != previous_state:
            self._log(f"[{self._name()}] state={previous_state} -> {state}")

        self._dispatch(state, results, frame)

    # ------------------------------------------------------------------
    # Action dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, state: str, results: dict, frame) -> None:
        if state == STATE_IN_RUN:
            if self._behavior_enabled("auto_farm_reset", default=True):
                self._check_auto_farm_reset(results)
            if self._behavior_enabled("end_run_reset", default=True):
                self._check_end_run_reset(results)
            self._check_cascade_reset(results)

        elif state == STATE_DEAD:
            self._handle_dead(results, frame)

        elif state == STATE_LOBBY:
            self._handle_lobby()

        elif state == STATE_UNKNOWN:
            self._check_crash_timeout()

    # ------------------------------------------------------------------
    # Timer logic
    # ------------------------------------------------------------------

    def _check_auto_farm_reset(self, results: dict) -> None:
        interval_s = self.cfg.timers.auto_farm_reset_interval_min * 60
        if time.time() - self._last_auto_reset < interval_s:
            return

        self._log(f"[{self._name()}] Auto-farm reset firing")

        auto_result = results.get("auto_button_on")
        detector_name = "auto_button_on"
        if not (auto_result and auto_result.found):
            auto_result = results.get("auto_button_off")
            detector_name = "auto_button_off"

        if not (auto_result and auto_result.found):
            self._log(f"[{self._name()}] Auto-farm reset: button not found; will retry")
            return

        target = auto_result.click_target(self._get_click_offset(detector_name))
        if not target:
            self._log(f"[{self._name()}] Auto-farm reset: no click target; will retry")
            return

        actions.double_tap(
            self.cfg.serial,
            target[0],
            target[1],
            adb_path=self.settings.adb_path,
        )
        self._last_auto_reset = time.time()
        self._log(f"[{self._name()}] Auto-farm double-tap sent at {target}")

    def _check_end_run_reset(self, results: dict) -> None:
        interval_s = self.cfg.timers.end_run_reset_interval_min * 60
        if time.time() - self._last_end_run_reset < interval_s:
            return

        self._log(f"[{self._name()}] End-run reset timer fired")
        self._execute_end_run(results)

    def _check_cascade_reset(self, results: dict) -> None:
        if self._pending_cascade_reset is None:
            return
        if time.time() < self._pending_cascade_reset:
            return

        self._log(f"[{self._name()}] Cascade reset firing (triggered by lead)")
        if self._execute_end_run(results, broadcast_cascade=False):
            self._pending_cascade_reset = None

    def _execute_end_run(self, results: Optional[dict] = None, broadcast_cascade: bool = True) -> bool:
        """Tap the detected end-run button and optionally notify support devices."""
        results = results or self._last_results
        end_result = results.get("end_run_button") if results else None

        if not (end_result and end_result.found):
            self._log(f"[{self._name()}] End-run button not found; action deferred")
            return False

        target = end_result.click_target(self._get_click_offset("end_run_button"))
        if not target:
            self._log(f"[{self._name()}] End-run button has no click target; action deferred")
            return False

        actions.tap(
            self.cfg.serial,
            target[0],
            target[1],
            adb_path=self.settings.adb_path,
        )
        self._last_end_run_reset = time.time()
        self._log(f"[{self._name()}] End-run tap sent at {target}")

        cascade_cfg = self.profile.behaviors.get("cascade_reset_on_end_run", {})
        if (
            broadcast_cascade
            and self.cfg.is_lead
            and cascade_cfg.get("enabled", False)
        ):
            delay_s = cascade_cfg.get("delay_after_lead_s", 30)
            self.event_bus.broadcast(
                event={"type": EVENT_CASCADE_RESET, "delay_s": delay_s},
                exclude_serial=self.cfg.serial,
            )
            self._log(f"[{self._name()}] Cascade reset broadcast sent (delay={delay_s}s)")

        return True

    # ------------------------------------------------------------------
    # State handlers
    # ------------------------------------------------------------------

    def _handle_dead(self, results: dict, frame) -> None:
        self._log(f"[{self._name()}] Handling DEAD state")

        eaten_cfg = self.profile.behaviors.get("eaten_by_detection", {})
        if eaten_cfg.get("enabled") and eaten_cfg.get("trigger_support_end_run"):
            self._check_eaten_by(frame)

        death_lobby = results.get("death_screen")
        if death_lobby and death_lobby.found:
            target = death_lobby.click_target(self._get_click_offset("death_screen"))
            if target:
                actions.tap(
                    self.cfg.serial,
                    target[0],
                    target[1],
                    adb_path=self.settings.adb_path,
                )
                self._log(f"[{self._name()}] Tapped death screen at {target}")

    def _handle_lobby(self) -> None:
        self._log(f"[{self._name()}] In lobby, rejoining private tank")
        link = self.settings.private_server_link
        if link:
            success = actions.join_server_by_link(
                self.cfg.serial,
                link,
                adb_path=self.settings.adb_path,
            )
            self._log(f"[{self._name()}] join_server_by_link success={success}")
        else:
            self._log(f"[{self._name()}] No private_server_link set — cannot rejoin")

    def _check_crash_timeout(self) -> None:
        if self._unknown_since is None:
            self._unknown_since = time.time()
            return

        elapsed = time.time() - self._unknown_since
        if elapsed > self._max_unknown_s:
            self._log(f"[{self._name()}] UNKNOWN for {elapsed:.0f}s — treating as crash")
            self._unknown_since = None
            self._recover_from_crash()

    # ------------------------------------------------------------------
    # Crash recovery
    # ------------------------------------------------------------------

    def _recover_from_crash(self) -> None:
        self._set_state(STATE_CRASHED)
        self._log(f"[{self._name()}] Crash recovery starting")

        actions.force_stop_roblox(self.cfg.serial, adb_path=self.settings.adb_path)
        if self._stop_event.wait(3.0):
            return

        launched = actions.launch_roblox(self.cfg.serial, adb_path=self.settings.adb_path)
        self._log(f"[{self._name()}] Roblox launched: {launched}")

    # ------------------------------------------------------------------
    # Eaten-by detection
    # ------------------------------------------------------------------

    def _check_eaten_by(self, frame) -> None:
        support_devices = [
            d for d in self.all_devices
            if not d.is_lead and d.serial != self.cfg.serial
        ]

        for dev in support_devices:
            if not dev.eaten_by_name_image:
                continue

            result = find_by_path(
                frame_bgr=frame,
                image_path=dev.eaten_by_name_image,
                bank=self.bank,
                threshold=self.settings.template_confidence_default,
                detector_name=f"eaten_by:{dev.nickname or dev.serial}",
            )

            if result.found:
                self._log(
                    f"[{self._name()}] Eaten by {dev.nickname or dev.serial} "
                    f"(score={result.score:.3f}) — sending force_end_run"
                )
                self.event_bus.post(
                    target_serial=dev.serial,
                    event={"type": EVENT_FORCE_END_RUN},
                )
                return

    # ------------------------------------------------------------------
    # Event bus handling
    # ------------------------------------------------------------------

    def _handle_events(self) -> None:
        events = self.event_bus.poll_all(self.cfg.serial)
        for event in events:
            etype = event.get("type")

            if etype == EVENT_CASCADE_RESET:
                delay_s = event.get("delay_s", 30)
                self._pending_cascade_reset = time.time() + delay_s
                self._log(f"[{self._name()}] Cascade reset scheduled in {delay_s}s")

            elif etype == EVENT_FORCE_END_RUN:
                self._log(f"[{self._name()}] Force end-run received from lead")
                if not self._execute_end_run(broadcast_cascade=False):
                    # Retry on the next IN_RUN scan when a fresh detector result is available.
                    self._pending_cascade_reset = time.time()

    # ------------------------------------------------------------------
    # Health state transitions
    # ------------------------------------------------------------------

    def _enter_battery_sleep(self) -> None:
        self._set_state(STATE_BATTERY_SLEEP)
        self._log(f"[{self._name()}] Battery critical ({self.health.battery_percent}%), entering sleep")

        actions.force_stop_roblox(self.cfg.serial, adb_path=self.settings.adb_path)
        if self._stop_event.wait(1.0):
            return
        actions.sleep_device(self.cfg.serial, adb_path=self.settings.adb_path)

        while not self._stop_event.is_set():
            if self._stop_event.wait(60.0):
                return
            health = self._health_monitor.check()
            with self._health_lock:
                self.health = health
            if health.battery_percent >= self.settings.health.battery_resume_percent:
                self._log(f"[{self._name()}] Battery recovered ({health.battery_percent}%), waking")
                actions.wake_device(self.cfg.serial, adb_path=self.settings.adb_path)
                if self._stop_event.wait(10.0):
                    return
                actions.launch_roblox(self.cfg.serial, adb_path=self.settings.adb_path)
                self._set_state(STATE_UNKNOWN)
                return

    def _enter_temp_pause(self) -> None:
        self._set_state(STATE_TEMP_PAUSE)
        self._log(f"[{self._name()}] Temperature critical ({self.health.temperature_celsius:.1f}°C), pausing")
        actions.sleep_device(self.cfg.serial, adb_path=self.settings.adb_path)

        while not self._stop_event.is_set():
            if self._stop_event.wait(30.0):
                return
            health = self._health_monitor.check()
            with self._health_lock:
                self.health = health
            if health.temperature_celsius < self.settings.health.temp_resume_celsius:
                self._log(f"[{self._name()}] Temperature recovered ({health.temperature_celsius:.1f}°C), resuming")
                actions.wake_device(self.cfg.serial, adb_path=self.settings.adb_path)
                self._set_state(STATE_UNKNOWN)
                return

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_state(self, state: str) -> None:
        if state != STATE_UNKNOWN:
            self._unknown_since = None
        self.current_state = state

    def _behavior_enabled(self, behavior_name: str, default: bool = False) -> bool:
        cfg = self.profile.behaviors.get(behavior_name, {})
        if isinstance(cfg, dict):
            return cfg.get("enabled", default)
        return bool(cfg)

    def _get_click_offset(self, detector_name: str) -> tuple:
        det = self.cfg.detectors.get(detector_name)
        if det and det.click_offset:
            return tuple(det.click_offset)
        return (0, 0)

    def _name(self) -> str:
        return self.cfg.nickname or self.cfg.serial[:8]

    def _log(self, msg: str) -> None:
        self._log_fn(msg)
