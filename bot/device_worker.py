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
from typing import Dict, List, Optional

from bot.config_manager import DeviceConfig, Settings, ProfileConfig
from bot.states import (
    STATE_IN_RUN, STATE_DEAD, STATE_LOBBY, STATE_LOADING,
    STATE_CRASHED, STATE_UNKNOWN,
    STATE_BATTERY_SLEEP, STATE_TEMP_PAUSE, STATE_ADB_LOST,
    SUSPENDED_STATES,
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
        all_device_cfgs: List[DeviceConfig],   # needed for eaten-by detection
        log_fn=None,                            # callable(str) for UI log output
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

        # Crash detection: track how long we've been in UNKNOWN or LOADING
        self._unknown_since: Optional[float] = None
        self._max_unknown_s = 60.0  # if UNKNOWN for > 60s, treat as crashed

        # Viewer process placeholder (Phase 2 scrcpy viewer)
        self.viewer_pid: Optional[int] = None

        # Current state (readable by UI)
        self.current_state: str = STATE_UNKNOWN

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

    def get_health(self) -> HealthStatus:
        """Thread-safe health status read for the UI."""
        with self._health_lock:
            return self.health

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        """The main worker loop. Runs until stop_event is set."""

        # Connect capture backend
        self._backend = make_backend(
            serial=self.cfg.serial,
            backend_type=self.cfg.capture_backend,
            adb_path=self.settings.adb_path,
        )
        if not self._backend.connect():
            self._log(f"[{self._name()}] Capture backend failed to connect. Worker exiting.")
            return

        while not self._stop_event.is_set():
            t0 = time.time()

            try:
                self._loop_iteration()
            except Exception as e:
                self._log(f"[{self._name()}] Unhandled error in loop: {type(e).__name__}: {e}")

            # Sleep to hit the target scan interval
            elapsed = time.time() - t0
            target_s = self.cfg.scan_interval_ms / 1000.0
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
            self._log(f"[{self._name()}] ADB disconnected, attempting reconnect...")
            reconnected = self._health_monitor.attempt_adb_reconnect()
            if not reconnected:
                return  # skip this iteration, try again next loop

        if health.battery_critical:
            self._enter_battery_sleep()
            return

        if health.temp_critical:
            self._enter_temp_pause()
            return

        # Throttle scan interval if temperature is high but not critical
        if health.temp_throttle:
            # We don't return here — just slow down by sleeping extra
            # The sleep at the end of _run() handles the normal interval;
            # we double it by setting a flag the sleep respects.
            pass  # handled implicitly by doubled scan interval in settings

        # ---- 2. Poll event bus ----
        self._handle_events()

        # ---- 3. Capture frame ----
        frame = self._backend.get_frame()
        if frame is None:
            self._log(f"[{self._name()}] Frame capture returned None, skipping iteration")
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

        if self.settings.debug.log_state_changes:
            self._log(f"[{self._name()}] state={state}")

        # ---- 6. Dispatch actions ----
        self._dispatch(state, results, frame)

    # ------------------------------------------------------------------
    # Action dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, state: str, results: dict, frame) -> None:
        """Route actions based on current state."""

        # Check timers first (they fire regardless of exact state if IN_RUN)
        if state == STATE_IN_RUN:
            self._check_auto_farm_reset(results)
            self._check_end_run_reset()
            self._check_cascade_reset()

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
        Fire the auto-farm reset if enough time has passed.
        Double-taps the auto button to toggle it off then back on,
        resetting the 20-minute server kick timer.
        """
        interval_s = self.cfg.timers.auto_farm_reset_interval_min * 60
        if time.time() - self._last_auto_reset < interval_s:
            return

        self._log(f"[{self._name()}] Auto-farm reset firing")

        # Find the auto button (could be on or off state)
        auto_result = results.get("auto_button_on") or results.get("auto_button_off")
        if auto_result and auto_result.found:
            offset = self._get_click_offset("auto_button_on")
            target = auto_result.click_target(offset)
            if target:
                actions.double_tap(self.cfg.serial, target[0], target[1],
                                   adb_path=self.settings.adb_path)
                self._log(f"[{self._name()}] Auto-farm double-tap sent at {target}")
        else:
            self._log(f"[{self._name()}] Auto-farm reset: button not found, skipping")

        self._last_auto_reset = time.time()

    def _check_end_run_reset(self) -> None:
        """Fire the end-run reset if the per-device timer has elapsed."""
        interval_s = self.cfg.timers.end_run_reset_interval_min * 60
        if time.time() - self._last_end_run_reset < interval_s:
            return

        self._log(f"[{self._name()}] End-run reset timer fired")
        self._execute_end_run()

    def _check_cascade_reset(self) -> None:
        """Fire a cascade reset if one was scheduled by the lead."""
        if self._pending_cascade_reset is None:
            return
        if time.time() < self._pending_cascade_reset:
            return

        self._log(f"[{self._name()}] Cascade reset firing (triggered by lead)")
        self._pending_cascade_reset = None
        self._execute_end_run()

    def _execute_end_run(self) -> None:
        """
        Tap the end-run button and broadcast cascade signal if this is the lead.
        The worker will pick up the DEAD state on the next loop iteration
        and handle the recovery sequence.
        """
        # Find end_run_button via detector result stored in last scan
        # We re-read it here via a quick single detector run if needed.
        # For now, use stored click_coords fallback if detector not in results.
        # The actual button tap uses the detector-derived coord.
        self._log(f"[{self._name()}] Executing end-run")

        # Broadcast cascade reset to all other devices if this is the lead
        if self.cfg.is_lead:
            delay_s = self.profile.behaviors.get(
                "cascade_reset_on_end_run", {}
            ).get("delay_after_lead_s", 30)

            self.event_bus.broadcast(
                event={
                    "type": EVENT_CASCADE_RESET,
                    "delay_s": delay_s,
                },
                exclude_serial=self.cfg.serial,
            )
            self._log(f"[{self._name()}] Cascade reset broadcast sent (delay={delay_s}s)")

        self._last_end_run_reset = time.time()
        # Actual button tap happens in _handle_dead → the state machine sees DEAD
        # and navigates back. We just need the button tap to initiate.
        # This is a placeholder — the full click sequence is in _handle_dead.

    # ------------------------------------------------------------------
    # State handlers
    # ------------------------------------------------------------------

    def _handle_dead(self, results: dict, frame) -> None:
        """Handle the DEAD state: eaten-by detection, then recovery."""
        self._log(f"[{self._name()}] Handling DEAD state")

        # Eaten-by detection (lead private only)
        behaviors = self.profile.behaviors
        eaten_cfg = behaviors.get("eaten_by_detection", {})
        if eaten_cfg.get("enabled") and eaten_cfg.get("trigger_support_end_run"):
            self._check_eaten_by(frame)

        # Navigate back to IN_RUN
        # Click the "death to lobby" button if detected, then rejoin
        death_lobby = results.get("death_screen")
        if death_lobby and death_lobby.found:
            offset = self._get_click_offset("death_screen")
            target = death_lobby.click_target(offset)
            if target:
                actions.tap(self.cfg.serial, target[0], target[1],
                            adb_path=self.settings.adb_path)
                self._log(f"[{self._name()}] Tapped death screen at {target}")

    def _handle_lobby(self) -> None:
        """Handle LOBBY state: rejoin the private tank."""
        self._log(f"[{self._name()}] In lobby, rejoining private tank")
        link = self.settings.private_server_link
        if link:
            success = actions.join_server_by_link(
                self.cfg.serial, link, adb_path=self.settings.adb_path
            )
            self._log(f"[{self._name()}] join_server_by_link success={success}")
        else:
            self._log(f"[{self._name()}] No private_server_link set — cannot rejoin")

    def _check_crash_timeout(self) -> None:
        """If UNKNOWN state persists too long, treat as crashed and recover."""
        if self._unknown_since is None:
            self._unknown_since = time.time()
            return

        elapsed = time.time() - self._unknown_since
        if elapsed > self._max_unknown_s:
            self._log(f"[{self._name()}] UNKNOWN for {elapsed:.0f}s — treating as crash")
            self._unknown_since = None
            self._recover_from_crash()
        else:
            # Not yet timed out — reset happens when we leave UNKNOWN
            pass

    # ------------------------------------------------------------------
    # Crash recovery
    # ------------------------------------------------------------------

    def _recover_from_crash(self) -> None:
        """Full crash recovery sequence."""
        self._set_state(STATE_CRASHED)
        self._log(f"[{self._name()}] Crash recovery starting")

        actions.force_stop_roblox(self.cfg.serial, adb_path=self.settings.adb_path)
        time.sleep(3.0)

        launched = actions.launch_roblox(self.cfg.serial, adb_path=self.settings.adb_path)
        self._log(f"[{self._name()}] Roblox launched: {launched}")

        # Wait for lobby state (up to 60s)
        # The next loop iterations will handle detecting LOBBY and rejoining

    # ------------------------------------------------------------------
    # Eaten-by detection
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
                self._log(
                    f"[{self._name()}] Cascade reset scheduled in {delay_s}s"
                )

            elif etype == EVENT_FORCE_END_RUN:
                self._log(f"[{self._name()}] Force end-run received from lead")
                self._execute_end_run()

    # ------------------------------------------------------------------
    # Health state transitions
    # ------------------------------------------------------------------

    def _enter_battery_sleep(self) -> None:
        """Device battery is critically low. Close Roblox and sleep."""
        self._set_state(STATE_BATTERY_SLEEP)
        self._log(f"[{self._name()}] Battery critical ({self.health.battery_percent}%), entering sleep")

        actions.force_stop_roblox(self.cfg.serial, adb_path=self.settings.adb_path)
        time.sleep(1.0)
        actions.sleep_device(self.cfg.serial, adb_path=self.settings.adb_path)

        # Poll battery until recovered
        while not self._stop_event.is_set():
            time.sleep(60.0)
            health = self._health_monitor.check()
            with self._health_lock:
                self.health = health
            if health.battery_percent >= self.settings.health.battery_resume_percent:
                self._log(f"[{self._name()}] Battery recovered ({health.battery_percent}%), waking")
                actions.wake_device(self.cfg.serial, adb_path=self.settings.adb_path)
                time.sleep(10.0)  # let device settle
                actions.launch_roblox(self.cfg.serial, adb_path=self.settings.adb_path)
                self._set_state(STATE_UNKNOWN)
                return

    def _enter_temp_pause(self) -> None:
        """Device is too hot. Pause the loop and let it cool."""
        self._set_state(STATE_TEMP_PAUSE)
        self._log(f"[{self._name()}] Temperature critical ({self.health.temperature_celsius:.1f}°C), pausing")
        actions.sleep_device(self.cfg.serial, adb_path=self.settings.adb_path)

        while not self._stop_event.is_set():
            time.sleep(30.0)
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
        """Update current state and reset the unknown timer if leaving UNKNOWN."""
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

    def _log(self, msg: str) -> None:
        """Send a log message through the log function (UI queue or print)."""
        self._log_fn(msg)
