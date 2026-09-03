"""
ui/settings_dialog.py

Global settings dialog.
Edits a copy of Settings and returns it on save.
The caller writes to disk and reloads the manager.

Tabbed via ttk.Notebook (General / ADB Timeouts / Health / Debug / Logging) —
same pattern ui/device_settings_dialog.py uses for the same problem (too many
rows for one flat, fixed-size dialog). Added in ROADMAP Phase 12 when the
[TUNABLE] AdbConfig/HealthConfig fields pushed the flat layout from ~29 rows
to ~43.
"""

from __future__ import annotations

import dataclasses
import tkinter as tk
from tkinter import ttk

from config.settings import Settings


class SettingsDialog:
    """Modal dialog for global settings."""

    def __init__(self, parent: tk.Tk, settings: Settings):
        # Kept for _save(): dataclasses.replace() off of these originals so
        # any field this dialog doesn't expose passes through unchanged
        # instead of silently resetting to its dataclass default on save.
        self._original = settings
        self.result: Settings = settings
        self.saved = False

        self.top = tk.Toplevel(parent)
        self.top.title("Global Settings")
        self.top.grab_set()
        self.top.resizable(False, False)

        # ---- Variables ----
        self._adb_path = tk.StringVar(value=settings.adb_path)
        self._server_link = tk.StringVar(value=settings.private_server_link)
        self._confidence = tk.DoubleVar(value=settings.template_confidence_default)
        self._backend = tk.StringVar(value=settings.capture_backend_default)
        self._scan_ms = tk.IntVar(value=settings.scan_interval_ms)
        self._development_mode = tk.BooleanVar(value=settings.development_mode)

        h = settings.health
        self._bat_min = tk.IntVar(value=h.battery_min_percent)
        self._bat_resume = tk.IntVar(value=h.battery_resume_percent)
        self._temp_throttle = tk.DoubleVar(value=h.temp_throttle_celsius)
        self._temp_pause = tk.DoubleVar(value=h.temp_pause_celsius)
        self._temp_resume = tk.DoubleVar(value=h.temp_resume_celsius)
        self._adb_reconnect = tk.IntVar(value=h.adb_reconnect_interval_s)

        # Device recovery/settle timing (Phase 3 HealthConfig fields, surfaced
        # in the UI as of Phase 12).
        self._crash_detect_after = tk.DoubleVar(value=h.crash_detect_after_s)
        self._crash_recovery_settle = tk.DoubleVar(value=h.crash_recovery_settle_s)
        self._battery_sleep_settle = tk.DoubleVar(value=h.battery_sleep_settle_s)
        self._battery_sleep_poll = tk.DoubleVar(value=h.battery_sleep_poll_s)
        self._wake_settle = tk.DoubleVar(value=h.wake_settle_s)
        self._temp_pause_poll = tk.DoubleVar(value=h.temp_pause_poll_s)
        self._thermal_throttle_mult = tk.DoubleVar(value=h.thermal_throttle_multiplier)
        self._health_check_slow = tk.DoubleVar(value=h.health_check_slow_threshold_s)

        a = settings.adb
        self._adb_quick_timeout = tk.DoubleVar(value=a.quick_timeout_s)
        self._adb_default_timeout = tk.DoubleVar(value=a.default_timeout_s)
        self._adb_launch_timeout = tk.DoubleVar(value=a.launch_timeout_s)
        self._adb_screencap_timeout = tk.DoubleVar(value=a.screencap_timeout_s)
        self._adb_screencap_batch_timeout = tk.DoubleVar(value=a.screencap_batch_timeout_s)
        self._adb_reconnect_settle = tk.DoubleVar(value=a.reconnect_settle_s)

        d = settings.debug
        self._debug_enabled = tk.BooleanVar(value=d.enabled)
        self._log_states = tk.BooleanVar(value=d.log_state_changes)
        self._log_detections = tk.BooleanVar(value=d.log_detections)
        self._log_actions = tk.BooleanVar(value=d.log_actions)
        self._log_health = tk.BooleanVar(value=d.log_health)
        self._log_config_reads = tk.BooleanVar(value=d.log_config_reads)
        self._screenshot_on_event = tk.BooleanVar(value=d.screenshot_on_event)
        self._save_failed = tk.BooleanVar(value=d.save_failed_captures)
        self._screenshot_dir = tk.StringVar(value=d.screenshot_dir)

        lg = settings.logging
        self._log_enabled = tk.BooleanVar(value=lg.enabled)
        self._log_level = tk.StringVar(value=lg.level)
        self._log_to_file = tk.BooleanVar(value=lg.log_to_file)
        self._log_to_console = tk.BooleanVar(value=lg.log_to_console)
        self._log_max_mb = tk.IntVar(value=lg.max_file_size_mb)
        self._log_backups = tk.IntVar(value=lg.backup_count)

        self._build()

    # ------------------------------------------------------------------
    # Shared per-tab helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _section(parent, text) -> None:
        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(10, 4))
        ttk.Label(parent, text=text, font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

    @staticmethod
    def _row(parent, label, widget_fn, *args, **kwargs) -> None:
        f = ttk.Frame(parent)
        f.pack(fill="x", pady=2)
        ttk.Label(f, text=label, width=30, anchor="w").pack(side="left")
        widget_fn(f, *args, **kwargs).pack(side="left", fill="x", expand=True)

    def _build(self) -> None:
        outer = ttk.Frame(self.top, padding=16)
        outer.pack(fill="both", expand=True)

        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)

        general_tab = ttk.Frame(notebook, padding=12)
        adb_tab = ttk.Frame(notebook, padding=12)
        health_tab = ttk.Frame(notebook, padding=12)
        debug_tab = ttk.Frame(notebook, padding=12)
        logging_tab = ttk.Frame(notebook, padding=12)

        notebook.add(general_tab, text="General")
        notebook.add(adb_tab, text="ADB Timeouts")
        notebook.add(health_tab, text="Health")
        notebook.add(debug_tab, text="Debug")
        notebook.add(logging_tab, text="Logging")

        self._build_general_tab(general_tab)
        self._build_adb_tab(adb_tab)
        self._build_health_tab(health_tab)
        self._build_debug_tab(debug_tab)
        self._build_logging_tab(logging_tab)

        # ---- Buttons ----
        ttk.Separator(outer, orient="horizontal").pack(fill="x", pady=(12, 8))
        btn_row = ttk.Frame(outer)
        btn_row.pack(anchor="e")
        ttk.Button(btn_row, text="Save", command=self._save).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Cancel", command=self.top.destroy).pack(side="left")

    # ------------------------------------------------------------------
    # Tabs
    # ------------------------------------------------------------------

    def _build_general_tab(self, tab: ttk.Frame) -> None:
        row = lambda *a, **kw: self._row(tab, *a, **kw)
        section = lambda *a, **kw: self._section(tab, *a, **kw)

        ttk.Label(tab, text="General", font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
        row("ADB Path:", ttk.Entry, textvariable=self._adb_path)
        row("Default Capture Backend:", lambda f, **kw: ttk.Combobox(
            f, textvariable=self._backend, values=["scrcpy", "adb"],
            state="readonly", width=12))
        row("Default Scan Interval (ms):", lambda f, **kw: ttk.Spinbox(
            f, from_=200, to=5000, increment=100, textvariable=self._scan_ms, width=8))
        row("Template Confidence:", lambda f, **kw: ttk.Spinbox(
            f, from_=0.50, to=1.00, increment=0.01, textvariable=self._confidence,
            format="%.2f", width=8))
        row("Development Mode:", lambda f, **kw: ttk.Checkbutton(
            f, variable=self._development_mode))
        ttk.Label(tab,
                  text="An unexpected error in a device's loop crashes that worker with a full\n"
                       "traceback instead of just logging it and continuing. Leave off for farm use.",
                  foreground="#888888", justify="left").pack(anchor="w", pady=(0, 4))

        section("Private Server")
        ttk.Label(tab, text="Private Server Link:", anchor="w").pack(anchor="w", pady=(4, 0))
        ttk.Entry(tab, textvariable=self._server_link, width=64).pack(fill="x", pady=(2, 0))
        ttk.Label(tab,
                  text="Paste your Roblox private server share URL here.\n"
                       "All devices use this to rejoin the private tank.",
                  foreground="#888888", justify="left").pack(anchor="w", pady=(2, 0))

    def _build_adb_tab(self, tab: ttk.Frame) -> None:
        row = lambda *a, **kw: self._row(tab, *a, **kw)

        ttk.Label(tab, text="ADB Command Timeouts (s)", font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
        ttk.Label(tab,
                  text="How long each tier of adb command waits before giving up. Increase for\n"
                       "slow or high-latency devices (e.g. the Pixel 3 over a weak USB hub).",
                  foreground="#888888", justify="left").pack(anchor="w", pady=(0, 6))
        row("Quick (status checks):", lambda f, **kw: ttk.Spinbox(
            f, from_=1.0, to=30.0, increment=0.5, textvariable=self._adb_quick_timeout,
            format="%.1f", width=8))
        row("Default (shell / input):", lambda f, **kw: ttk.Spinbox(
            f, from_=1.0, to=60.0, increment=0.5, textvariable=self._adb_default_timeout,
            format="%.1f", width=8))
        row("Launch (app / deep-link):", lambda f, **kw: ttk.Spinbox(
            f, from_=1.0, to=60.0, increment=0.5, textvariable=self._adb_launch_timeout,
            format="%.1f", width=8))
        row("Screencap:", lambda f, **kw: ttk.Spinbox(
            f, from_=1.0, to=30.0, increment=0.5, textvariable=self._adb_screencap_timeout,
            format="%.1f", width=8))
        row("Screencap (batch tool):", lambda f, **kw: ttk.Spinbox(
            f, from_=1.0, to=60.0, increment=0.5, textvariable=self._adb_screencap_batch_timeout,
            format="%.1f", width=8))
        row("Reconnect Settle:", lambda f, **kw: ttk.Spinbox(
            f, from_=0.0, to=10.0, increment=0.5, textvariable=self._adb_reconnect_settle,
            format="%.1f", width=8))

    def _build_health_tab(self, tab: ttk.Frame) -> None:
        row = lambda *a, **kw: self._row(tab, *a, **kw)
        section = lambda *a, **kw: self._section(tab, *a, **kw)

        ttk.Label(tab, text="Battery Thresholds", font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
        row("Min % (sleep below):", lambda f, **kw: ttk.Spinbox(
            f, from_=5, to=50, textvariable=self._bat_min, width=6))
        row("Resume % (wake at):", lambda f, **kw: ttk.Spinbox(
            f, from_=20, to=100, textvariable=self._bat_resume, width=6))

        section("Temperature Thresholds (°C)")
        row("Throttle above:", lambda f, **kw: ttk.Spinbox(
            f, from_=35, to=70, increment=1, textvariable=self._temp_throttle, width=6))
        row("Pause above:", lambda f, **kw: ttk.Spinbox(
            f, from_=40, to=80, increment=1, textvariable=self._temp_pause, width=6))
        row("Resume below:", lambda f, **kw: ttk.Spinbox(
            f, from_=30, to=65, increment=1, textvariable=self._temp_resume, width=6))
        row("ADB Reconnect Interval (s):", lambda f, **kw: ttk.Spinbox(
            f, from_=5, to=60, textvariable=self._adb_reconnect, width=6))

        section("Device Recovery Timing (s)")
        ttk.Label(tab,
                  text="How long the worker waits at each step of crash recovery, battery sleep,\n"
                       "and thermal pause. The farm spans a Pixel 3 to a Pixel 8a — slower devices\n"
                       "may need more settle time than these defaults assume.",
                  foreground="#888888", justify="left").pack(anchor="w", pady=(0, 6))
        row("Crash Detect After:", lambda f, **kw: ttk.Spinbox(
            f, from_=10.0, to=300.0, increment=5.0, textvariable=self._crash_detect_after,
            format="%.1f", width=8))
        row("Crash Recovery Settle:", lambda f, **kw: ttk.Spinbox(
            f, from_=0.0, to=30.0, increment=0.5, textvariable=self._crash_recovery_settle,
            format="%.1f", width=8))
        row("Battery Sleep Settle:", lambda f, **kw: ttk.Spinbox(
            f, from_=0.0, to=10.0, increment=0.5, textvariable=self._battery_sleep_settle,
            format="%.1f", width=8))
        row("Battery Sleep Poll:", lambda f, **kw: ttk.Spinbox(
            f, from_=5.0, to=300.0, increment=5.0, textvariable=self._battery_sleep_poll,
            format="%.1f", width=8))
        row("Wake Settle:", lambda f, **kw: ttk.Spinbox(
            f, from_=0.0, to=60.0, increment=1.0, textvariable=self._wake_settle,
            format="%.1f", width=8))
        row("Temp Pause Poll:", lambda f, **kw: ttk.Spinbox(
            f, from_=5.0, to=120.0, increment=5.0, textvariable=self._temp_pause_poll,
            format="%.1f", width=8))
        row("Thermal Throttle Multiplier (×):", lambda f, **kw: ttk.Spinbox(
            f, from_=1.0, to=5.0, increment=0.1, textvariable=self._thermal_throttle_mult,
            format="%.1f", width=8))
        row("Health Check Slow Threshold:", lambda f, **kw: ttk.Spinbox(
            f, from_=0.5, to=10.0, increment=0.5, textvariable=self._health_check_slow,
            format="%.1f", width=8))
        ttk.Label(tab,
                  text="How long a single ADB call inside a health check can take before it's\n"
                       "logged as a WARNING — separate from the ADB Timeouts tab's hard timeouts.",
                  foreground="#888888", justify="left").pack(anchor="w", pady=(4, 0))

    def _build_debug_tab(self, tab: ttk.Frame) -> None:
        # Live "what's happening right now" output — distinct from Logging,
        # the persistent on-disk record. Every category here adds
        # supplementary detail on top of the always-on log lines; none of
        # them gate or replace anything you'd otherwise see.
        row = lambda *a, **kw: self._row(tab, *a, **kw)

        ttk.Label(tab, text="Debug", font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
        row("Enabled (master switch):", lambda f, **kw: ttk.Checkbutton(
            f, variable=self._debug_enabled))
        ttk.Label(tab,
                  text="Categories below only produce output while Enabled is checked.",
                  foreground="#888888", justify="left").pack(anchor="w", pady=(0, 4))
        row("Log State Changes:", lambda f, **kw: ttk.Checkbutton(
            f, variable=self._log_states))
        row("Log Detections:", lambda f, **kw: ttk.Checkbutton(
            f, variable=self._log_detections))
        row("Log Actions:", lambda f, **kw: ttk.Checkbutton(
            f, variable=self._log_actions))
        row("Log Health:", lambda f, **kw: ttk.Checkbutton(
            f, variable=self._log_health))
        row("Log Config Reads:", lambda f, **kw: ttk.Checkbutton(
            f, variable=self._log_config_reads))
        row("Screenshot on Event:", lambda f, **kw: ttk.Checkbutton(
            f, variable=self._screenshot_on_event))
        row("Save Failed Captures:", lambda f, **kw: ttk.Checkbutton(
            f, variable=self._save_failed))
        row("Screenshot Directory:", ttk.Entry, textvariable=self._screenshot_dir)

    def _build_logging_tab(self, tab: ttk.Frame) -> None:
        # Persistent on-disk record (logs/app.log, logs/errors.log) — distinct
        # from Debug, which is live "what is the app doing right now" output.
        row = lambda *a, **kw: self._row(tab, *a, **kw)

        ttk.Label(tab, text="Logging", font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
        row("Enabled:", lambda f, **kw: ttk.Checkbutton(
            f, variable=self._log_enabled))
        row("Minimum Level:", lambda f, **kw: ttk.Combobox(
            f, textvariable=self._log_level,
            values=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            state="readonly", width=10))
        row("Log to File:", lambda f, **kw: ttk.Checkbutton(
            f, variable=self._log_to_file))
        row("Log to Console:", lambda f, **kw: ttk.Checkbutton(
            f, variable=self._log_to_console))
        row("Max File Size (MB):", lambda f, **kw: ttk.Spinbox(
            f, from_=1, to=100, textvariable=self._log_max_mb, width=6))
        row("Backup Count:", lambda f, **kw: ttk.Spinbox(
            f, from_=0, to=20, textvariable=self._log_backups, width=6))
        ttk.Label(tab,
                  text="errors.log always records ERROR/CRITICAL regardless of these settings.",
                  foreground="#888888", justify="left").pack(anchor="w", pady=(2, 0))

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _save(self) -> None:
        # dataclasses.replace() off self._original's nested configs rather
        # than constructing fresh HealthConfig/AdbConfig/DebugConfig objects
        # — any field this dialog doesn't expose carries through unchanged
        # instead of resetting to its dataclass default on every save.
        self.result = dataclasses.replace(
            self._original,
            adb_path=self._adb_path.get().strip(),
            private_server_link=self._server_link.get().strip(),
            scan_interval_ms=self._scan_ms.get(),
            template_confidence_default=self._confidence.get(),
            capture_backend_default=self._backend.get(),
            development_mode=self._development_mode.get(),
            health=dataclasses.replace(
                self._original.health,
                battery_min_percent=self._bat_min.get(),
                battery_resume_percent=self._bat_resume.get(),
                temp_throttle_celsius=self._temp_throttle.get(),
                temp_pause_celsius=self._temp_pause.get(),
                temp_resume_celsius=self._temp_resume.get(),
                adb_reconnect_interval_s=self._adb_reconnect.get(),
                crash_detect_after_s=self._crash_detect_after.get(),
                crash_recovery_settle_s=self._crash_recovery_settle.get(),
                battery_sleep_settle_s=self._battery_sleep_settle.get(),
                battery_sleep_poll_s=self._battery_sleep_poll.get(),
                wake_settle_s=self._wake_settle.get(),
                temp_pause_poll_s=self._temp_pause_poll.get(),
                thermal_throttle_multiplier=self._thermal_throttle_mult.get(),
                health_check_slow_threshold_s=self._health_check_slow.get(),
            ),
            adb=dataclasses.replace(
                self._original.adb,
                quick_timeout_s=self._adb_quick_timeout.get(),
                default_timeout_s=self._adb_default_timeout.get(),
                launch_timeout_s=self._adb_launch_timeout.get(),
                screencap_timeout_s=self._adb_screencap_timeout.get(),
                screencap_batch_timeout_s=self._adb_screencap_batch_timeout.get(),
                reconnect_settle_s=self._adb_reconnect_settle.get(),
            ),
            debug=dataclasses.replace(
                self._original.debug,
                enabled=self._debug_enabled.get(),
                log_state_changes=self._log_states.get(),
                log_detections=self._log_detections.get(),
                log_actions=self._log_actions.get(),
                log_health=self._log_health.get(),
                log_config_reads=self._log_config_reads.get(),
                screenshot_on_event=self._screenshot_on_event.get(),
                save_failed_captures=self._save_failed.get(),
                screenshot_dir=self._screenshot_dir.get().strip(),
            ),
            logging=dataclasses.replace(
                self._original.logging,
                enabled=self._log_enabled.get(),
                level=self._log_level.get(),
                log_to_file=self._log_to_file.get(),
                log_to_console=self._log_to_console.get(),
                max_file_size_mb=self._log_max_mb.get(),
                backup_count=self._log_backups.get(),
            ),
        )
        self.saved = True
        self.top.destroy()
