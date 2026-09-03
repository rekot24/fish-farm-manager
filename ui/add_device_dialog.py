"""
ui/add_device_dialog.py

Add Device dialog.

Discovers ADB-connected devices not already in devices.json,
presents them for the user to configure, and adds them on confirm.
"""

from __future__ import annotations

import subprocess
import tkinter as tk
from tkinter import ttk, messagebox
from typing import List, Optional

from config.devices import DeviceConfig, TimerConfig, load_devices, save_devices
from config.constants import ADB_DEFAULT_TIMEOUT_S, ROLE_LEAD, ROLE_SUPPORT

PROFILES = ["support_private", "lead_private", "support_public", "lead_public"]


class AddDeviceDialog:
    """
    Scans for connected ADB devices, filters out ones already configured,
    and lets the user name and profile each new device before adding.
    """

    def __init__(self, parent, adb_path: str = "adb"):
        self.adb_path = adb_path
        self.added: List[DeviceConfig] = []
        self.saved = False

        self.top = tk.Toplevel(parent)
        self.top.title("Add Devices")
        self.top.grab_set()
        self.top.resizable(False, False)
        self.top.geometry("560x420")

        self._rows: List[_DeviceRow] = []
        self._build()
        self._scan()

    def _build(self) -> None:
        outer = ttk.Frame(self.top, padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        # Header
        ttk.Label(
            outer,
            text="New ADB-connected devices found:",
            font=("TkDefaultFont", 10, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        # Scrollable device list
        list_frame = ttk.Frame(outer, relief="sunken", borderwidth=1)
        list_frame.grid(row=1, column=0, sticky="nsew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        canvas = tk.Canvas(list_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._row_container = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=self._row_container, anchor="nw")
        self._row_container.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        self._canvas = canvas

        # Status label
        self._lbl_status = ttk.Label(outer, text="Scanning...", foreground="#888888")
        self._lbl_status.grid(row=2, column=0, sticky="w", pady=(6, 0))

        # Buttons
        btn_row = ttk.Frame(outer)
        btn_row.grid(row=3, column=0, sticky="e", pady=(10, 0))
        ttk.Button(btn_row, text="Add Selected",
                   command=self._add_selected).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Cancel",
                   command=self.top.destroy).pack(side="left")

    def _scan(self) -> None:
        """Find ADB devices not already in devices.json."""
        existing_serials = {d.serial for d in load_devices()}

        try:
            result = subprocess.run(
                [self.adb_path, "devices"],
                capture_output=True, timeout=ADB_DEFAULT_TIMEOUT_S, text=True,
            )
            new_serials = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line or line.startswith("List of"):
                    continue
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "device":
                    serial = parts[0]
                    if serial not in existing_serials:
                        new_serials.append(serial)
        except Exception as e:
            self._lbl_status.config(text=f"ADB scan failed: {e}", foreground="red")
            return

        if not new_serials:
            self._lbl_status.config(
                text="No new devices found. Check USB connection and USB debugging.",
                foreground="#888888"
            )
            return

        # Build a row for each new device
        # Column headers
        header = ttk.Frame(self._row_container, padding=(6, 4))
        header.pack(fill="x")
        ttk.Label(header, text="✓", width=3).pack(side="left")
        ttk.Label(header, text="Serial", width=20).pack(side="left")
        ttk.Label(header, text="Nickname", width=18).pack(side="left", padx=(8, 0))
        ttk.Label(header, text="Profile", width=18).pack(side="left", padx=(8, 0))
        ttk.Label(header, text="Lead?", width=6).pack(side="left", padx=(8, 0))
        ttk.Separator(self._row_container, orient="horizontal").pack(fill="x")

        for serial in new_serials:
            row = _DeviceRow(self._row_container, serial)
            row.pack(fill="x", padx=4, pady=2)
            self._rows.append(row)

        self._lbl_status.config(
            text=f"{len(new_serials)} new device(s) found. Configure and click Add Selected.",
            foreground="#00aa44"
        )

    def _add_selected(self) -> None:
        """Validate and save all checked device rows."""
        selected = [r for r in self._rows if r.include.get()]
        if not selected:
            messagebox.showwarning("Nothing selected",
                                   "Check at least one device to add.", parent=self.top)
            return

        # Enforce one-lead rule across existing + new
        existing = load_devices()
        existing_has_lead = any(d.role == ROLE_LEAD for d in existing)
        new_leads = [r for r in selected if r.role_is_lead.get()]

        if existing_has_lead and new_leads:
            names = ", ".join(r.serial[:12] for r in new_leads)
            messagebox.showerror(
                "Lead conflict",
                f"A lead device is already configured.\n"
                f"Cannot also mark these as lead: {names}\n\n"
                f"Uncheck 'Lead?' for the new devices, or remove the existing lead first.",
                parent=self.top
            )
            return

        if len(new_leads) > 1:
            messagebox.showerror(
                "Lead conflict",
                "Only one device can be the lead. Uncheck 'Lead?' for all but one.",
                parent=self.top
            )
            return

        # Build DeviceConfig for each selected row
        new_cfgs = []
        for row in selected:
            nickname = row.nickname.get().strip() or row.serial[:12]
            profile = row.profile.get()
            role = ROLE_LEAD if row.role_is_lead.get() else ROLE_SUPPORT

            # Auto-correct profile/lead mismatch
            if role == ROLE_LEAD and "support" in profile:
                profile = "lead_private"
            if role == ROLE_SUPPORT and "lead" in profile:
                profile = "support_private"

            new_cfgs.append(DeviceConfig(
                serial=row.serial,
                nickname=nickname,
                model="",
                enabled=True,
                role=role,
                profile=profile,
                capture_backend="scrcpy",
                scan_interval_ms=800,
                detectors={},
                timers=TimerConfig(),
                eaten_by_name_image="",
                device_image_overrides=[],
                notes="",
            ))

        # Save
        all_devices = existing + new_cfgs
        save_devices(all_devices)
        self.added = new_cfgs
        self.saved = True
        self.top.destroy()


class _DeviceRow(ttk.Frame):
    """One row in the Add Device list."""

    def __init__(self, parent, serial: str):
        super().__init__(parent, padding=(6, 3))
        self.serial = serial

        self.include = tk.BooleanVar(value=True)
        self.nickname = tk.StringVar(value="")
        self.profile = tk.StringVar(value="support_private")
        # Checkbox widget stays boolean; converted to ROLE_LEAD/ROLE_SUPPORT
        # in _add_selected() when the DeviceConfig is actually built.
        self.role_is_lead = tk.BooleanVar(value=False)

        ttk.Checkbutton(self, variable=self.include, width=2).pack(side="left")
        ttk.Label(self, text=serial[:20], width=20,
                  font=("TkFixedFont", 9)).pack(side="left")
        ttk.Entry(self, textvariable=self.nickname,
                  width=18).pack(side="left", padx=(8, 0))
        ttk.Combobox(self, textvariable=self.profile,
                     values=PROFILES, state="readonly",
                     width=16).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(self, variable=self.role_is_lead,
                        width=4).pack(side="left", padx=(8, 0))
