"""
ui/app.py

Main Tkinter application window.

Layout:
  - Top bar: Start All / Stop All / Add Devices / Settings buttons
  - Device list: scrollable panel of DevicePanel rows
  - Log panel: scrolled text with filter

Workers never touch Tkinter directly.
All UI updates happen via root.after() polling at 500ms intervals.
All config writes go through config.settings/config.devices save functions.
"""

from __future__ import annotations

import queue
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, scrolledtext
from typing import List, Optional

from bot import app_logger
from bot.device_manager import DeviceManager
from config.paths import project_root
from config.settings import load_settings, save_settings
from config.devices import load_devices, save_devices
from ui.device_panel import DevicePanel
from ui.settings_dialog import SettingsDialog


class App:
    """Main application window."""

    POLL_INTERVAL_MS = 500    # how often to refresh device status from workers
    LOG_MAX_LINES = 500       # max lines to keep in the log panel

    # UI layout constants — local to this file (not config/constants.py):
    # facts about how this one window renders, not app configuration.
    RESIZE_DEBOUNCE_MS = 100         # delay before _resize_to_fit runs after adding a device panel
    LOG_DRAIN_INTERVAL_MS = 100      # how often the log queue is drained into the log panel
    MAX_VISIBLE_DEVICES_FOR_RESIZE = 10   # cap the window's auto-resize growth at this many device rows
    DEVICE_PANEL_HEIGHT_PX = 78      # must match DevicePanel's actual rendered row height
    LOG_PANEL_HEIGHT_PX = 220        # fixed height reserved for the log panel
    TOP_BAR_HEIGHT_PX = 60           # fixed height reserved for the top button bar

    def __init__(self, root: tk.Tk, manager: DeviceManager, startup_warnings: List[str] = None):
        self.root = root
        self.manager = manager
        self.root.title("Be Fish Farm Manager")
        self.root.geometry("820x680")
        self.root.minsize(640, 480)

        # Thread-safe log queue — workers call app.log() which puts here
        self._log_queue: queue.Queue = queue.Queue()

        # Device panel widgets — serial -> DevicePanel
        self._device_panels: dict[str, DevicePanel] = {}

        self._build_ui()
        self._rebuild_device_panels()

        # Show startup warnings in the log panel. Display only, not log() —
        # main.py already wrote these to app_logger before this App existed;
        # calling log() here would write them to the file a second time.
        if startup_warnings:
            for w in startup_warnings:
                self.display(f"[WARNING] {w}")

        # Start polling loops
        self._poll_status()
        self._drain_log_queue()

        # Clean shutdown on window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        self.root.rowconfigure(2, weight=0)

        # ---- Top bar ----
        top = ttk.Frame(self.root, padding=(10, 8))
        top.grid(row=0, column=0, sticky="ew")

        ttk.Label(top, text="Be Fish Farm Manager",
                  font=("TkDefaultFont", 12, "bold")).pack(side="left")

        ttk.Button(top, text="Settings",
                   command=self._open_settings).pack(side="right", padx=(4, 0))
        ttk.Button(top, text="Stop All",
                   command=self._stop_all).pack(side="right", padx=(4, 0))
        ttk.Button(top, text="Start All",
                   command=self._start_all).pack(side="right", padx=(4, 0))
        ttk.Button(top, text="+ Add Devices",
                   command=self._add_devices).pack(side="right", padx=(4, 12))

        # ---- Device list ----
        device_frame = ttk.LabelFrame(self.root, text="Devices", padding=(8, 6))
        device_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 4))
        device_frame.columnconfigure(0, weight=1)
        device_frame.rowconfigure(0, weight=1)

        # Scrollable canvas for device panels
        self._canvas = tk.Canvas(device_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(device_frame, orient="vertical",
                                   command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.grid(row=0, column=1, sticky="ns")
        self._canvas.grid(row=0, column=0, sticky="nsew")

        self._device_container = ttk.Frame(self._canvas)
        self._canvas_window = self._canvas.create_window(
            (0, 0), window=self._device_container, anchor="nw"
        )
        self._device_container.bind("<Configure>", self._on_frame_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)

        # Placeholder shown when no devices are configured
        self._lbl_no_devices = ttk.Label(
            self._device_container,
            text='No devices configured. Click "+ Add Devices" to scan for connected devices.',
            foreground="#888888",
            padding=(12, 20),
        )

        # ---- Log panel ----
        log_frame = ttk.LabelFrame(self.root, text="Log", padding=(8, 6))
        log_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        log_frame.columnconfigure(0, weight=1)

        self._log_text = scrolledtext.ScrolledText(
            log_frame, height=10, wrap="word", state="disabled"
        )
        self._log_text.grid(row=0, column=0, columnspan=3, sticky="ew")

        filter_frame = ttk.Frame(log_frame)
        filter_frame.grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(filter_frame, text="Filter:").pack(side="left")
        self._log_filter = tk.StringVar()
        ttk.Entry(filter_frame, textvariable=self._log_filter,
                  width=20).pack(side="left", padx=(4, 0))
        ttk.Button(filter_frame, text="Clear Log",
                   command=self._clear_log).pack(side="left", padx=(8, 0))

    def _rebuild_device_panels(self) -> None:
        """Rebuild the device panel list from current device configs."""
        for widget in self._device_container.winfo_children():
            widget.destroy()
        self._device_panels.clear()

        statuses = self.manager.get_all_statuses()

        if not statuses:
            self._lbl_no_devices = ttk.Label(
                self._device_container,
                text='No devices configured. Click "+ Add Devices" to scan for connected devices.',
                foreground="#888888",
                padding=(12, 20),
            )
            self._lbl_no_devices.pack(anchor="w")
            return

        for i, status in enumerate(statuses):
            serial = status["serial"]
            panel = DevicePanel(
                parent=self._device_container,
                status=status,
                on_toggle=lambda s=serial: self._toggle_device(s),
                on_settings=lambda s=serial: self._open_device_settings(s),
                on_end_run=lambda s=serial: self._manual_end_run(s),
            )
            panel.grid(row=i, column=0, sticky="ew", pady=(0, 2))
            self._device_container.columnconfigure(0, weight=1)
            self._device_panels[serial] = panel
            self.root.after(self.RESIZE_DEBOUNCE_MS, self._resize_to_fit)

    def _resize_to_fit(self) -> None:
        """Resize window to fit current number of devices, capped at MAX_VISIBLE_DEVICES_FOR_RESIZE."""
        device_count = len(self._device_panels)
        capped = min(device_count, self.MAX_VISIBLE_DEVICES_FOR_RESIZE)
        panel_height = capped * self.DEVICE_PANEL_HEIGHT_PX
        total = panel_height + self.LOG_PANEL_HEIGHT_PX + self.TOP_BAR_HEIGHT_PX
        self.root.geometry(f"820x{total}")

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    def _poll_status(self) -> None:
        """Poll worker status and update device panels every POLL_INTERVAL_MS."""
        statuses = self.manager.get_all_statuses()
        for status in statuses:
            serial = status["serial"]
            panel = self._device_panels.get(serial)
            if panel:
                timer_info = self.manager.get_timer_info(serial)
                panel.update(status, timer_info)

        self.root.after(self.POLL_INTERVAL_MS, self._poll_status)

    def _drain_log_queue(self) -> None:
        """Drain the log queue and append messages to the log text widget."""
        flt = self._log_filter.get().lower().strip()
        try:
            while True:
                msg = self._log_queue.get_nowait()
                if flt and flt not in msg.lower():
                    continue
                self._append_log(msg)
        except queue.Empty:
            pass
        self.root.after(self.LOG_DRAIN_INTERVAL_MS, self._drain_log_queue)

    # ------------------------------------------------------------------
    # Log helpers
    # ------------------------------------------------------------------

    def log(self, msg: str, level: str = "INFO") -> None:
        """
        Thread-safe log. Workers and manager call this as their log_fn.
        Writes to the persistent logger (file/console per settings) and
        queues the message for display in the log panel.
        """
        app_logger.log(msg, level)
        self._log_queue.put(msg)

    def display(self, msg: str) -> None:
        """
        Queue a message for the log panel only — no write to app_logger.
        Used to replay messages that were already logged before the UI
        existed (see main.py), so they aren't written to the file twice.
        """
        self._log_queue.put(msg)

    def _append_log(self, msg: str) -> None:
        """Append a line to the log text widget (main thread only)."""
        self._log_text.configure(state="normal")
        self._log_text.insert("end", msg + "\n")

        # Trim to max lines
        lines = int(self._log_text.index("end-1c").split(".")[0])
        if lines > self.LOG_MAX_LINES:
            self._log_text.delete("1.0", f"{lines - self.LOG_MAX_LINES}.0")

        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")

    # ------------------------------------------------------------------
    # Button actions
    # ------------------------------------------------------------------

    def _start_all(self) -> None:
        self.log("[UI] Starting all devices...")
        self.manager.start_all()

    def _stop_all(self) -> None:
        self.log("[UI] Stopping all devices...")
        self.manager.stop_all()

    def _add_devices(self) -> None:
        """Open the Add Devices dialog to scan and add new ADB devices."""
        from ui.add_device_dialog import AddDeviceDialog
        settings = load_settings()
        dialog = AddDeviceDialog(self.root, adb_path=settings.adb_path)
        self.root.wait_window(dialog.top)

        if dialog.saved and dialog.added:
            # Reload configs and update the manager
            new_devices = load_devices()
            self.manager.reload_device_configs(new_devices)
            self._rebuild_device_panels()
            names = ", ".join(d.nickname or d.serial[:12] for d in dialog.added)
            self.log(f"[UI] Added {len(dialog.added)} device(s): {names}")
        elif dialog.saved:
            self.log("[UI] No devices were added.")

    def _toggle_device(self, serial: str) -> None:
        """Start or stop a single device worker."""
        if self.manager.is_device_running(serial):
            self.manager.stop_device(serial)
            self.log(f"[UI] Stopped {serial}")
        else:
            self.manager.start_device(serial)
            self.log(f"[UI] Starting {serial}")

    def _manual_end_run(self, serial: str) -> None:
        """Manually trigger an end-run on a device."""
        if self.manager.trigger_end_run(serial):
            self.log(f"[UI] Manual end-run requested for {serial}")
        else:
            self.log(f"[UI] Manual end-run failed: {serial} is not running", "WARNING")

    def _open_settings(self) -> None:
        """Open the global settings dialog."""
        settings = load_settings()
        dialog = SettingsDialog(self.root, settings)
        self.root.wait_window(dialog.top)
        if dialog.saved:
            save_settings(dialog.result)
            self.manager.reload_settings(dialog.result)
            self.log("[UI] Global settings saved")

    def _open_device_settings(self, serial: str) -> None:
        """Open the per-device settings dialog."""
        from ui.device_settings_dialog import DeviceSettingsDialog
        devices = load_devices()
        dev_cfg = next((d for d in devices if d.serial == serial), None)
        if not dev_cfg:
            return

        dialog = DeviceSettingsDialog(self.root, dev_cfg, all_devices=devices)
        self.root.wait_window(dialog.top)
        if dialog.saved:
            updated = [dialog.result if d.serial == serial else d for d in devices]
            save_devices(updated)
            self.manager.reload_device_configs(updated)
            self._rebuild_device_panels()
            self.log(f"[UI] Device settings saved for {dev_cfg.nickname or serial}")
        elif dialog.deleted:
            self._remove_device(serial)

    def _remove_device(self, serial: str) -> None:
        """
        Permanently remove a device: stop its worker, delete its captured
        detector images, drop it from devices.json, and refresh the UI.
        Called after the Device Settings dialog's Danger Zone confirmation
        (dialog.deleted) — the dialog itself never performs the deletion.
        """
        self.manager.stop_device(serial)

        assets_dir = project_root() / "assets" / "devices" / serial
        shutil.rmtree(assets_dir, ignore_errors=True)

        devices = load_devices()
        filtered = [d for d in devices if d.serial != serial]
        save_devices(filtered)
        self.manager.reload_device_configs(filtered)
        self._rebuild_device_panels()
        self.log(f"[UI] Removed device {serial} and deleted its assets")

    # ------------------------------------------------------------------
    # Scrollable device list helpers
    # ------------------------------------------------------------------

    def _on_frame_configure(self, event) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self._canvas.itemconfig(self._canvas_window, width=event.width)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def _on_close(self) -> None:
        """Called when the user closes the window."""
        self.log("[UI] Shutting down...")
        self.manager.stop_all()
        self.root.destroy()
