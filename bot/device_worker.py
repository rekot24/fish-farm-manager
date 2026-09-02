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

Workers never touch Tkinter. UI reads status via polling.
Inter-device communication goes through FarmEventBus only.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from config.devices import DeviceConfig
from config.profiles import ProfileConfig
from config.settings import Settings
from bot.states import (
    STATE_IN_RUN, STATE_DEAD, STATE_LOBBY, STATE_LOADING,
    STATE_CRASHED, STATE_UNKNOWN,
    STATE_BATTERY_SLEEP, STATE_TEMP_PAUSE, STATE_ADB_LOST,
    SUSPENDED_STATES,
)
from bot.state_machine import resolve_state
from bot.farm_event_bus import FarmEventBus, EVENT_CASCADE_RESET, EVENT_FORCE_END_RUN, EVENT_MOVE_TO_PRIVATE
from bot.health_monitor import HealthMonitor, HealthStatus
from bot import actions
from capture import make_backend
from capture.base import CaptureBackend
from detection.detector import run_all_detectors, find_by_path
from detection.template_bank import TemplateBank


def _default_log_fn(msg: str, level: str = "INFO") -> None:
    """Fallback log_fn when none is supplied — used mainly by tests/standalone use."""
    print(f"[{level}] {msg}")


class DeviceWorker:
    """
    Manages one device's bot loop in a background thread.

    Lifecycle:
        worker = DeviceWorker(...)
        worker.start()     # spawns background thread
        ...
        worker.stop()      # signals thread to exit, waits for join
    """

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

        self._log_fn = log_fn or _default_log_fn
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Public status — UI reads this via polling, worker writes it
        self.health: HealthStatus = HealthStatus(serial=device_cfg.serial)
        self._health_lock = threading.Lock()

        # Capture backend
        self._backend: Optional[CaptureBackend] = None

        # Health monitor
        self._health_monitor = HealthMonitor(
            serial=device_cfg.serial,
            adb_path=settings.adb_path,
            cfg=settings.health,
        )

        # Timer tracking
        self._last_auto_reset = time.time()
        self._last_end_run_reset = time.time()
        self._pending_cascade_reset: Optional[float] = None  # timestamp when to fire

        # Crash detection: track how long we've been in UNKNOWN
        self._unknown_since: Optional[float] = None
        self._max_unknown_s = 60.0

        # Public mode: per-session revive counter (starts at configured max, never persisted)
        self.revives_remaining: int = device_cfg.revive_count

        # Current state (readable by UI)
        self.current_state: str = STATE_UNKNOWN

        # Previous state for change-only logging
        self._prev_state: str = STATE_UNKNOWN

    # ------------------------------------------------------------------
    # Public thread control
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the worker thread."""
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
        """Signal the worker thread to stop and wait for it to exit."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        if self._backend:
            self._backend.disconnect()
        self._log(f"Worker stopped for {self.cfg.nickname or self.cfg.serial}")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def request_manual_end_run(self) -> None:
        """
        Request an end-run on this device's next scan iteration.

        Public entry point for a UI-triggered manual end-run. Reuses the same
        mechanism as an incoming EVENT_FORCE_END_RUN (expire the timer so the
        next loop iteration fires it) rather than calling _execute_end_run()
        directly — that method needs a fresh detector `results` dict that
        only exists inside the loop, so calling it from outside the loop
        with no results would fail.
        """
        self._last_end_run_reset = 0

    def get_health(self) -> HealthStatus:
        """Thread-safe health status read for the UI."""
        with self._health_lock:
            return self.health

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        """The main worker loop. Runs until stop_event is set."""
        self._backend = make_backend(
            serial=self.cfg.serial,
            backend_type=self.cfg.capture_backend,
            adb_path=self.settings.adb_path,
        )
        if not self._backend.connect():
            self._log(f"[{self._name()}] Capture backend failed to connect. Worker exiting.", "ERROR")
            return

        while not self._stop_event.is_set():
            t0 = time.time()

            try:
                self._loop_iteration()
            except Exception as e:
                self._log(f"[{self._name()}] Unhandled error in loop: {type(e).__name__}: {e}", "ERROR")

            elapsed = time.time() - t0
            target_s = self.cfg.scan_interval_ms / 1000.0
            # Double scan interval while temperature is elevated but not critical
            if self.health.temp_throttle:
                target_s *= 2.0
            sleep_s = max(0.05, target_s - elapsed)
            self._stop_event.wait(timeout=sleep_s)

        if self._backend:
            self._backend.disconnect()

    def _loop_iteration(self) -> None:
        """One full scan-detect-act iteration."""

        # ---- 1. Health check ----
        health = self._health_monitor.check()
        with self._health_lock:
            self.health = health

        if not health.adb_connected:
            self._set_state(STATE_ADB_LOST)
            self._log(f"[{self._name()}] ADB disconnected, attempting reconnect...", "WARNING")
            self._health_monitor.attempt_adb_reconnect()
            return

        if health.battery_critical:
            self._enter_battery_sleep()
            return

        if health.temp_critical:
            self._enter_temp_pause()
            return

        # ---- 2. Poll event bus ----
        self._handle_events()

        # ---- 3. Capture frame ----
        frame = self._backend.get_frame()
        if frame is None:
            self._log(f"[{self._name()}] Frame capture returned None, skipping iteration", "WARNING")
            return

        # ---- 4. Run detectors ----
        detector_names = self.profile.detectors_required
        results = run_all_detectors(
            detector_names=detector_names,
            frame_bgr=frame,
            device_serial=self.cfg.serial,
            device_overrides=self.cfg.device_image_overrides,
            bank=self.bank,
            threshold=self.settings.template_confidence_default,
        )

        # ---- 5. Resolve state ----
        state = resolve_state(results, self.profile.profile_name)
        self._set_state(state)

        # Log only on state transitions
        if self.settings.debug.log_state_changes and state != self._prev_state:
            self._log(f"[{self._name()}] state: {self._prev_state} → {state}")
        self._prev_state = state

        # ---- 6. Dispatch actions ----
        self._dispatch(state, results, frame)

    # ------------------------------------------------------------------
    # Action dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, state: str, results: dict, frame) -> None:
        """Route actions based on current state."""

        if state == STATE_IN_RUN:
            self._check_auto_farm_reset(results)
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
        """
        Fire the auto-farm reset if the timer has elapsed and the feature is enabled.
        Double-taps the auto button to toggle it off then back on,
        resetting the server kick timer.
        """
        if not self.cfg.timers.auto_farm_reset_enabled:
            return

        interval_s = self.cfg.timers.auto_farm_reset_interval_min * 60
        if time.time() - self._last_auto_reset < interval_s:
            return

        self._log(f"[{self._name()}] Auto-farm reset firing")

        auto_result = results.get("auto_button_on") or results.get("auto_button_off")
        if auto_result and auto_result.found:
            offset = self._get_click_offset("auto_button_on")
            target = auto_result.click_target(offset)
            if target:
                actions.double_tap(self.cfg.serial, target[0], target[1],
                                   adb_path=self.settings.adb_path)
                self._log(f"[{self._name()}] Auto-farm double-tap sent at {target}")
                self._last_auto_reset = time.time()
            else:
                self._log(f"[{self._name()}] Auto-farm reset: could not resolve click target", "WARNING")
        else:
            self._log(f"[{self._name()}] Auto-farm reset: button not found, will retry next cycle", "WARNING")
            # Do NOT advance the timer — retry next scan

    def _check_end_run_reset(self, results: dict) -> None:
        """
        Fire the end-run reset if the timer has elapsed and the feature is enabled.
        Clicks the end-run button directly.
        """
        if not self.cfg.timers.end_run_reset_enabled:
            return

        interval_s = self.cfg.timers.end_run_reset_interval_min * 60
        if time.time() - self._last_end_run_reset < interval_s:
            return

        self._log(f"[{self._name()}] End-run reset timer fired")
        self._execute_end_run(results)

    def _check_cascade_reset(self, results: dict) -> None:
        """Fire a cascade reset if one was scheduled by the lead."""
        if self._pending_cascade_reset is None:
            return
        if time.time() < self._pending_cascade_reset:
            return

        self._log(f"[{self._name()}] Cascade reset firing (triggered by lead)")
        self._pending_cascade_reset = None
        self._execute_end_run(results)

    def _execute_end_run(self, results: dict) -> None:
        """
        Tap the end-run button.
        If this is the lead device, broadcast a cascade reset to supports.
        Timer is only advanced after a successful tap.
        """
        self._log(f"[{self._name()}] Executing end-run")

        end_run_result = results.get("end_run_button")
        if not end_run_result or not end_run_result.found:
            self._log(f"[{self._name()}] End-run button not found, will retry next cycle", "WARNING")
            return  # Do NOT advance timer — retry next scan

        offset = self._get_click_offset("end_run_button")
        target = end_run_result.click_target(offset)
        if not target:
            self._log(f"[{self._name()}] End-run: could not resolve click target", "WARNING")
            return

        actions.tap(self.cfg.serial, target[0], target[1],
                    adb_path=self.settings.adb_path)
        self._log(f"[{self._name()}] End-run button tapped at {target}")

        # Advance timer only after successful tap
        self._last_end_run_reset = time.time()

        # Lead broadcasts cascade reset to supports
        if self.cfg.is_lead:
            behaviors = self.profile.behaviors
            cascade_cfg = behaviors.get("cascade_reset_on_end_run", {})
            if cascade_cfg.get("enabled", True):
                delay_s = cascade_cfg.get("delay_after_lead_s", 30)
                self.event_bus.broadcast(
                    event={"type": EVENT_CASCADE_RESET, "delay_s": delay_s},
                    exclude_serial=self.cfg.serial,
                )
                self._log(f"[{self._name()}] Cascade reset broadcast (delay={delay_s}s)")

    # ------------------------------------------------------------------
    # State handlers
    # ------------------------------------------------------------------

    def _handle_dead(self, results: dict, frame) -> None:
        """
        Handle DEAD state. Behavior differs by server type:

        Private mode:
          - Lead only: check eaten-by and send force_end_run to responsible support
          - Navigate back to lobby and rejoin

        Public mode:
          1. Turn off auto-farm (priority — always first)
          2. Save a screenshot
          3. If revive enabled and revives remain: attempt revive, decrement counter
          4. If revives exhausted: move to private, broadcast EVENT_MOVE_TO_PRIVATE to supports
        """
        server_type = self.profile.server_type
        self._log(f"[{self._name()}] Handling DEAD state (server_type={server_type})")

        if server_type == "private":
            self._handle_dead_private(results, frame)
        else:
            self._handle_dead_public(results, frame)

    def _handle_dead_private(self, results: dict, frame) -> None:
        """Dead state handling for private mode."""
        behaviors = self.profile.behaviors

        # Lead only: eaten-by detection
        if self.cfg.is_lead:
            eaten_cfg = behaviors.get("eaten_by_detection", {})
            if eaten_cfg.get("enabled") and eaten_cfg.get("trigger_support_end_run"):
                self._check_eaten_by(frame)

        # Navigate back to lobby
        death_result = results.get("death_screen")
        if death_result and death_result.found:
            offset = self._get_click_offset("death_screen")
            target = death_result.click_target(offset)
            if target:
                actions.tap(self.cfg.serial, target[0], target[1],
                            adb_path=self.settings.adb_path)
                self._log(f"[{self._name()}] Tapped death screen at {target}")

    def _handle_dead_public(self, results: dict, frame) -> None:
        """Dead state handling for public mode."""
        behaviors = self.profile.behaviors
        dead_cfg = behaviors.get("dead_state", {})

        # Step 1: Turn off auto-farm (always, top priority)
        if dead_cfg.get("disable_auto_on_death", True):
            auto_on = results.get("auto_button_on")
            if auto_on and auto_on.found:
                offset = self._get_click_offset("auto_button_on")
                target = auto_on.click_target(offset)
                if target:
                    actions.tap(self.cfg.serial, target[0], target[1],
                                adb_path=self.settings.adb_path)
                    self._log(f"[{self._name()}] Auto-farm turned off on death at {target}")

        # Step 2: Save screenshot
        if dead_cfg.get("save_screenshot", True):
            self._save_death_screenshot(frame)

        # Step 3: Revive or move to private
        if dead_cfg.get("revive_enabled", False) and self.revives_remaining > 0:
            revive_result = results.get("revive_button")
            if revive_result and revive_result.found:
                offset = self._get_click_offset("revive_button")
                target = revive_result.click_target(offset)
                if target:
                    actions.tap(self.cfg.serial, target[0], target[1],
                                adb_path=self.settings.adb_path)
                    self.revives_remaining -= 1
                    self._log(
                        f"[{self._name()}] Revived. Revives remaining: {self.revives_remaining}"
                    )
            else:
                self._log(f"[{self._name()}] Revive button not found", "WARNING")
        else:
            # Revives exhausted (or not enabled) — move to private
            self._log(
                f"[{self._name()}] Revives exhausted ({self.revives_remaining}), moving to private"
            )
            self._move_to_private(broadcast=self.cfg.is_lead)

    def _move_to_private(self, broadcast: bool = False) -> None:
        """Join the private server and optionally broadcast the signal to supports."""
        link = self.settings.private_server_link
        if link:
            success = actions.join_server_by_link(
                self.cfg.serial, link, adb_path=self.settings.adb_path
            )
            self._log(f"[{self._name()}] Moving to private server, success={success}",
                       "INFO" if success else "ERROR")
        else:
            self._log(f"[{self._name()}] No private_server_link set — cannot move to private", "WARNING")

        if broadcast:
            self.event_bus.broadcast(
                event={"type": EVENT_MOVE_TO_PRIVATE},
                exclude_serial=self.cfg.serial,
            )
            self._log(f"[{self._name()}] Broadcast EVENT_MOVE_TO_PRIVATE to supports")

    def _handle_lobby(self) -> None:
        """Handle LOBBY state: rejoin the private tank."""
        self._log(f"[{self._name()}] In lobby, rejoining private tank")
        link = self.settings.private_server_link
        if link:
            success = actions.join_server_by_link(
                self.cfg.serial, link, adb_path=self.settings.adb_path
            )
            self._log(f"[{self._name()}] join_server_by_link success={success}",
                       "INFO" if success else "ERROR")
        else:
            self._log(f"[{self._name()}] No private_server_link set — cannot rejoin", "WARNING")

    def _check_crash_timeout(self) -> None:
        """If UNKNOWN state persists too long, treat as crashed and recover."""
        if self._unknown_since is None:
            self._unknown_since = time.time()
            return

        elapsed = time.time() - self._unknown_since
        if elapsed > self._max_unknown_s:
            self._log(f"[{self._name()}] UNKNOWN for {elapsed:.0f}s — treating as crash", "ERROR")
            self._unknown_since = None
            self._recover_from_crash()

    # ------------------------------------------------------------------
    # Crash recovery
    # ------------------------------------------------------------------

    def _recover_from_crash(self) -> None:
        """Full crash recovery: force-stop Roblox and relaunch."""
        self._set_state(STATE_CRASHED)
        self._log(f"[{self._name()}] Crash recovery starting", "WARNING")

        actions.force_stop_roblox(self.cfg.serial, adb_path=self.settings.adb_path)
        self._stop_event.wait(timeout=3.0)

        launched = actions.launch_roblox(self.cfg.serial, adb_path=self.settings.adb_path)
        self._log(f"[{self._name()}] Roblox launched: {launched}", "INFO" if launched else "ERROR")
        # Next loop iterations handle detecting LOBBY and rejoining

    # ------------------------------------------------------------------
    # Eaten-by detection (lead private only)
    # ------------------------------------------------------------------

    def _check_eaten_by(self, frame) -> None:
        """
        On the lead's death screen, check if a support device ate the lead.
        If found, post a force_end_run event to that device.
        """
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
                return  # only one eater possible

    # ------------------------------------------------------------------
    # Screenshot helper
    # ------------------------------------------------------------------

    def _save_death_screenshot(self, frame) -> None:
        """Save a screenshot on death to the configured debug directory."""
        try:
            import cv2
            screenshot_dir = Path(self.settings.debug.screenshot_dir)
            screenshot_dir.mkdir(parents=True, exist_ok=True)

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            name = self.cfg.nickname or self.cfg.serial[:8]
            filename = screenshot_dir / f"death_{name}_{ts}.png"
            cv2.imwrite(str(filename), frame)
            self._log(f"[{self._name()}] Death screenshot saved: {filename}")
        except Exception as e:
            self._log(f"[{self._name()}] Failed to save death screenshot: {e}", "ERROR")

    # ------------------------------------------------------------------
    # Event bus handling
    # ------------------------------------------------------------------

    def _handle_events(self) -> None:
        """Drain and handle all pending events from the FarmEventBus."""
        events = self.event_bus.poll_all(self.cfg.serial)
        for event in events:
            etype = event.get("type")

            if etype == EVENT_CASCADE_RESET:
                delay_s = event.get("delay_s", 30)
                fire_at = time.time() + delay_s
                self._pending_cascade_reset = fire_at
                self._log(f"[{self._name()}] Cascade reset scheduled in {delay_s}s")

            elif etype == EVENT_FORCE_END_RUN:
                self._log(f"[{self._name()}] Force end-run received from lead")
                # We don't have fresh results here — will fire on next scan
                # by setting the timer to expire immediately
                self._last_end_run_reset = 0

            elif etype == EVENT_MOVE_TO_PRIVATE:
                self._log(f"[{self._name()}] Move-to-private received from lead")
                self._move_to_private(broadcast=False)

    # ------------------------------------------------------------------
    # Health state transitions
    # ------------------------------------------------------------------

    def _enter_battery_sleep(self) -> None:
        """Device battery is critically low. Close Roblox and sleep."""
        self._set_state(STATE_BATTERY_SLEEP)
        self._log(f"[{self._name()}] Battery critical ({self.health.battery_percent}%), entering sleep", "WARNING")

        actions.force_stop_roblox(self.cfg.serial, adb_path=self.settings.adb_path)
        self._stop_event.wait(timeout=1.0)
        actions.sleep_device(self.cfg.serial, adb_path=self.settings.adb_path)

        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=60.0)
            health = self._health_monitor.check()
            with self._health_lock:
                self.health = health
            if health.battery_percent >= self.settings.health.battery_resume_percent:
                self._log(f"[{self._name()}] Battery recovered ({health.battery_percent}%), waking")
                actions.wake_device(self.cfg.serial, adb_path=self.settings.adb_path)
                self._stop_event.wait(timeout=10.0)
                actions.launch_roblox(self.cfg.serial, adb_path=self.settings.adb_path)
                self._set_state(STATE_UNKNOWN)
                return

    def _enter_temp_pause(self) -> None:
        """Device is too hot. Pause and let it cool."""
        self._set_state(STATE_TEMP_PAUSE)
        self._log(f"[{self._name()}] Temperature critical ({self.health.temperature_celsius:.1f}°C), pausing", "WARNING")
        actions.sleep_device(self.cfg.serial, adb_path=self.settings.adb_path)

        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=30.0)
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
        """Update current state and reset the UNKNOWN timer when leaving UNKNOWN."""
        if state != STATE_UNKNOWN:
            self._unknown_since = None
        self.current_state = state

    def _get_click_offset(self, detector_name: str) -> tuple:
        """Get the click_offset for a detector from device config."""
        det = self.cfg.detectors.get(detector_name)
        if det and det.click_offset:
            return tuple(det.click_offset)
        return (0, 0)

    def _name(self) -> str:
        """Short display name for log lines."""
        return self.cfg.nickname or self.cfg.serial[:8]

    def _log(self, msg: str, level: str = "INFO") -> None:
        """Send a log message through the log function (UI queue or print)."""
        self._log_fn(msg, level)
