"""
ui/device_settings_dialog.py

Per-device settings dialog.
Allows editing nickname, profile, lead toggle, capture backend, timers.
Does NOT allow editing click offsets inline — those come from the Image Capture Tool.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from typing import List

from config.devices import DeviceConfig, TimerConfig


PROFILES = ["lead_private", "support_private", "lead_public", "support_public"]
BACKENDS = ["scrcpy", "adb"]


class DeviceSettingsDialog:
    """Modal dialog for one device's settings."""

    def __init__(self, parent, device_cfg: DeviceConfig, all_devices: List[DeviceConfig]):
        self.result: DeviceConfig = device_cfg
        self.all_devices = all_devices
        self.saved = False

        self.top = tk.Toplevel(parent)
        self.top.title(f"Device Settings — {device_cfg.nickname or device_cfg.serial}")
        self.top.grab_set()
        self.top.resizable(False, False)

        # ---- Variables ----
        self._nickname   = tk.StringVar(value=device_cfg.nickname)
        self._notes      = tk.StringVar(value=device_cfg.notes)
        self._profile    = tk.StringVar(value=device_cfg.profile)
        self._is_lead    = tk.BooleanVar(value=device_cfg.is_lead)
        self._backend    = tk.StringVar(value=device_cfg.capture_backend)
        self._scan_ms    = tk.IntVar(value=device_cfg.scan_interval_ms)

        self._auto_enabled  = tk.BooleanVar(value=device_cfg.timers.auto_farm_reset_enabled)
        self._auto_interval = tk.IntVar(value=device_cfg.timers.auto_farm_reset_interval_min)
        self._end_enabled   = tk.BooleanVar(value=device_cfg.timers.end_run_reset_enabled)
        self._end_interval  = tk.IntVar(value=device_cfg.timers.end_run_reset_interval_min)

        self._revive_count = tk.IntVar(value=device_cfg.revive_count)

        self._build()

    def _build(self) -> None:
        outer = ttk.Frame(self.top, padding=16)
        outer.pack(fill="both", expand=True)

        def lbl_entry(label, var, width=28):
            f = ttk.Frame(outer)
            f.pack(fill="x", pady=3)
            ttk.Label(f, text=label, width=26, anchor="w").pack(side="left")
            ttk.Entry(f, textvariable=var, width=width).pack(side="left")

        def lbl_combo(label, var, values, width=20):
            f = ttk.Frame(outer)
            f.pack(fill="x", pady=3)
            ttk.Label(f, text=label, width=26, anchor="w").pack(side="left")
            ttk.Combobox(f, textvariable=var, values=values,
                         state="readonly", width=width).pack(side="left")

        def lbl_spin(label, var, from_, to, step=1, width=8):
            f = ttk.Frame(outer)
            f.pack(fill="x", pady=3)
            ttk.Label(f, text=label, width=26, anchor="w").pack(side="left")
            ttk.Spinbox(f, from_=from_, to=to, increment=step,
                        textvariable=var, width=width).pack(side="left")

        # ---- Identity ----
        ttk.Label(outer, text="Identity",
                  font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

        lbl_entry("Nickname:", self._nickname)
        lbl_entry("Notes:", self._notes, width=40)

        f = ttk.Frame(outer)
        f.pack(fill="x", pady=3)
        ttk.Label(f, text="Serial:", width=26, anchor="w").pack(side="left")
        ttk.Label(f, text=self.result.serial, foreground="#888888").pack(side="left")

        # ---- Role & Profile ----
        ttk.Separator(outer, orient="horizontal").pack(fill="x", pady=(10, 4))
        ttk.Label(outer, text="Role & Profile",
                  font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

        lbl_combo("Profile:", self._profile, PROFILES)

        f = ttk.Frame(outer)
        f.pack(fill="x", pady=3)
        ttk.Label(f, text="Is Lead Device:", width=26, anchor="w").pack(side="left")
        ttk.Checkbutton(f, variable=self._is_lead).pack(side="left")
        ttk.Label(f, text="(only one device may be lead)",
                  foreground="#888888").pack(side="left", padx=(6, 0))

        # ---- Capture & Scan ----
        ttk.Separator(outer, orient="horizontal").pack(fill="x", pady=(10, 4))
        ttk.Label(outer, text="Capture & Scan",
                  font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

        lbl_combo("Capture Backend:", self._backend, BACKENDS, width=12)
        lbl_spin("Scan Interval (ms):", self._scan_ms, 200, 5000, 100)

        # ---- Timers ----
        ttk.Separator(outer, orient="horizontal").pack(fill="x", pady=(10, 4))
        ttk.Label(outer, text="Timers",
                  font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

        # Auto-farm reset row with enabled toggle
        f = ttk.Frame(outer)
        f.pack(fill="x", pady=3)
        ttk.Label(f, text="Auto-Farm Reset:", width=26, anchor="w").pack(side="left")
        ttk.Checkbutton(f, text="Enabled", variable=self._auto_enabled).pack(side="left")
        ttk.Label(f, text="Interval (min):").pack(side="left", padx=(12, 4))
        ttk.Spinbox(f, from_=1, to=60, textvariable=self._auto_interval,
                    width=6).pack(side="left")

        # End-run reset row with enabled toggle
        f = ttk.Frame(outer)
        f.pack(fill="x", pady=3)
        ttk.Label(f, text="End-Run Reset:", width=26, anchor="w").pack(side="left")
        ttk.Checkbutton(f, text="Enabled", variable=self._end_enabled).pack(side="left")
        ttk.Label(f, text="Interval (min):").pack(side="left", padx=(12, 4))
        ttk.Spinbox(f, from_=1, to=120, textvariable=self._end_interval,
                    width=6).pack(side="left")

        # ---- Public mode ----
        ttk.Separator(outer, orient="horizontal").pack(fill="x", pady=(10, 4))
        ttk.Label(outer, text="Public Mode",
                  font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

        f = ttk.Frame(outer)
        f.pack(fill="x", pady=3)
        ttk.Label(f, text="Revive Count:", width=26, anchor="w").pack(side="left")
        ttk.Spinbox(f, from_=0, to=99, textvariable=self._revive_count,
                    width=6).pack(side="left")
        ttk.Label(f, text="(0 = disabled; resets to this value on app restart)",
                  foreground="#888888").pack(side="left", padx=(8, 0))

        # ---- Setup Tools ----
        ttk.Separator(outer, orient="horizontal").pack(fill="x", pady=(10, 4))
        ttk.Label(outer, text="Setup Tools",
                  font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

        tools_row = ttk.Frame(outer)
        tools_row.pack(anchor="w", pady=4)
        ttk.Button(
            tools_row, text="Open Detector Tool",
            command=self._open_capture_tool,
        ).pack(side="left", padx=(0, 8))

        # ---- Save / Cancel ----
        ttk.Separator(outer, orient="horizontal").pack(fill="x", pady=(12, 8))
        btn_row = ttk.Frame(outer)
        btn_row.pack(anchor="e")
        ttk.Button(btn_row, text="Save",
                   command=self._save).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Cancel",
                   command=self.top.destroy).pack(side="left")

    def _save(self) -> None:
        # Enforce one-lead rule
        if self._is_lead.get():
            other_leads = [
                d for d in self.all_devices
                if d.is_lead and d.serial != self.result.serial
            ]
            if other_leads:
                names = ", ".join(d.nickname or d.serial for d in other_leads)
                if not messagebox.askyesno(
                    "Lead Change",
                    f"Devices currently set as lead: {names}\n\n"
                    f"Setting this device as lead will de-select the others. Continue?",
                    parent=self.top,
                ):
                    return
                for d in self.all_devices:
                    if d.serial != self.result.serial:
                        d.is_lead = False

        self.result = DeviceConfig(
            serial=self.result.serial,
            nickname=self._nickname.get().strip(),
            model=self.result.model,
            enabled=self.result.enabled,
            is_lead=self._is_lead.get(),
            profile=self._profile.get(),
            capture_backend=self._backend.get(),
            scan_interval_ms=self._scan_ms.get(),
            detectors=self.result.detectors,
            timers=TimerConfig(
                auto_farm_reset_enabled=self._auto_enabled.get(),
                auto_farm_reset_interval_min=self._auto_interval.get(),
                end_run_reset_enabled=self._end_enabled.get(),
                end_run_reset_interval_min=self._end_interval.get(),
            ),
            eaten_by_name_image=self.result.eaten_by_name_image,
            device_image_overrides=self.result.device_image_overrides,
            revive_count=self._revive_count.get(),
            notes=self._notes.get().strip(),
        )
        self.saved = True
        self.top.destroy()

    def _open_capture_tool(self) -> None:
        """Launch the Detector Tool for this device."""
        from tools.image_capture_tool import ImageCaptureTool
        ImageCaptureTool(
            self.top,
            device_cfg=self.result,
            all_device_cfgs=self.all_devices,
        )
