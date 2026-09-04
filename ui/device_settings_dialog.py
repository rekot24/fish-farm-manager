"""
ui/device_settings_dialog.py

Per-device settings dialog, tabbed (ttk.Notebook):
  General   — identity, role & profile, capture & scan, public mode, setup tools
  Timers    — auto-farm reset, end-run reset, cascade reset
  Actions   — death-behavior flags; eaten-by rows show/hide live by role (Phase 11)
  Health    — per-device battery/temp protection toggles (Phase 11)
  Detectors — per-device disable checklist, populated from the assigned
              profile's detectors_required, rebuilt live if Profile changes

Tabbed rather than one long flat page — the same problem
tools/image_capture_tool.py already solved the same way, once Detectors/
Actions/Health/the missing Timers row got added on top of the original
Identity/Role/Capture/Public Mode/Setup Tools content.

"Save as Preset..." / "Load Preset..." (bottom button row, always visible
regardless of active tab) operate on the dialog's in-memory state via
_build_result()/_apply_to_widgets() — no need to Save/Cancel first.

Does NOT allow editing click offsets inline — those come from the Image Capture Tool.
"""

from __future__ import annotations

import dataclasses
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from typing import Dict, List, Optional

from config.devices import DeviceConfig
from config.constants import ROLE_LEAD, ROLE_SUPPORT
from config.profiles import load_profile
from config import presets as presets_mod


PROFILES = ["lead_private", "support_private", "lead_public", "support_public"]
BACKENDS = ["scrcpy", "adb"]


class DeviceSettingsDialog:
    """Modal dialog for one device's settings."""

    def __init__(self, parent, device_cfg: DeviceConfig, all_devices: List[DeviceConfig]):
        self.result: DeviceConfig = device_cfg
        self.all_devices = all_devices
        self.saved = False
        self.deleted = False

        self.top = tk.Toplevel(parent)
        self.top.title(f"Device Settings — {device_cfg.nickname or device_cfg.serial}")
        self.top.grab_set()
        self.top.resizable(False, False)

        # ---- Variables ----
        self._nickname = tk.StringVar(value=device_cfg.nickname)
        self._notes = tk.StringVar(value=device_cfg.notes)
        self._profile = tk.StringVar(value=device_cfg.profile)
        # Checkbox widget stays boolean — device_cfg.role (ROLE_LEAD/ROLE_SUPPORT)
        # converts to/from it at the load/save boundary below.
        self._role_is_lead = tk.BooleanVar(value=device_cfg.role == ROLE_LEAD)
        self._backend = tk.StringVar(value=device_cfg.capture_backend)
        self._scan_ms = tk.IntVar(value=device_cfg.scan_interval_ms)
        self._revive_count = tk.IntVar(value=device_cfg.revive_count)

        t = device_cfg.timers
        self._auto_enabled = tk.BooleanVar(value=t.auto_farm_reset_enabled)
        self._auto_interval = tk.IntVar(value=t.auto_farm_reset_interval_min)
        self._end_enabled = tk.BooleanVar(value=t.end_run_reset_enabled)
        self._end_interval = tk.IntVar(value=t.end_run_reset_interval_min)
        self._cascade_enabled = tk.BooleanVar(value=t.cascade_reset_enabled)
        self._cascade_delay = tk.DoubleVar(value=t.cascade_reset_delay_after_lead_s)

        db = device_cfg.death_behavior
        self._disable_auto_on_death = tk.BooleanVar(value=db.disable_auto_on_death)
        self._save_screenshot_on_death = tk.BooleanVar(value=db.save_screenshot_on_death)
        self._revive_enabled = tk.BooleanVar(value=db.revive_enabled)
        self._eaten_by_enabled = tk.BooleanVar(value=db.eaten_by_detection_enabled)
        self._eaten_by_trigger = tk.BooleanVar(value=db.eaten_by_detection_trigger_support_end_run)

        hr = device_cfg.health_response
        self._battery_protection = tk.BooleanVar(value=hr.battery_protection_enabled)
        self._temp_protection = tk.BooleanVar(value=hr.temp_protection_enabled)

        # Detector checkboxes: one BooleanVar per detector name in the
        # CURRENT profile's detectors_required, rebuilt whenever the
        # Profile combo changes (private/public lists differ).
        self._detector_vars: Dict[str, tk.BooleanVar] = {}
        self._initial_disabled_detectors = set(device_cfg.disabled_detectors)

        self._build()

        # Live reactivity: role affects which Actions rows are usable
        # (Phase 8's captured requirement); profile affects which
        # detectors exist to toggle.
        self._role_is_lead.trace_add("write", lambda *a: self._update_role_dependent_rows())
        self._profile.trace_add("write", lambda *a: self._rebuild_detector_checklist())
        self._update_role_dependent_rows()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self) -> None:
        outer = ttk.Frame(self.top, padding=12)
        outer.pack(fill="both", expand=True)

        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)

        general_tab = ttk.Frame(notebook, padding=12)
        timers_tab = ttk.Frame(notebook, padding=12)
        actions_tab = ttk.Frame(notebook, padding=12)
        health_tab = ttk.Frame(notebook, padding=12)
        detectors_tab = ttk.Frame(notebook, padding=12)

        notebook.add(general_tab, text="General")
        notebook.add(timers_tab, text="Timers")
        notebook.add(actions_tab, text="Actions")
        notebook.add(health_tab, text="Health")
        notebook.add(detectors_tab, text="Detectors")

        self._build_general_tab(general_tab)
        self._build_timers_tab(timers_tab)
        self._build_actions_tab(actions_tab)
        self._build_health_tab(health_tab)
        self._build_detectors_tab(detectors_tab)

        # ---- Save / Cancel / Presets — always visible, not tab-scoped ----
        ttk.Separator(outer, orient="horizontal").pack(fill="x", pady=(10, 8))
        btn_row = ttk.Frame(outer)
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="Save", command=self._save).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Cancel", command=self.top.destroy).pack(side="left")
        ttk.Button(btn_row, text="Save as Preset...", command=self._save_as_preset).pack(side="right", padx=(8, 0))
        ttk.Button(btn_row, text="Load Preset...", command=self._load_preset).pack(side="right")

    def _build_general_tab(self, parent: ttk.Frame) -> None:
        def lbl_entry(label, var, width=28):
            f = ttk.Frame(parent)
            f.pack(fill="x", pady=3)
            ttk.Label(f, text=label, width=20, anchor="w").pack(side="left")
            ttk.Entry(f, textvariable=var, width=width).pack(side="left")

        def lbl_combo(label, var, values, width=20):
            f = ttk.Frame(parent)
            f.pack(fill="x", pady=3)
            ttk.Label(f, text=label, width=20, anchor="w").pack(side="left")
            ttk.Combobox(f, textvariable=var, values=values,
                         state="readonly", width=width).pack(side="left")

        def lbl_spin(label, var, from_, to, step=1, width=8):
            f = ttk.Frame(parent)
            f.pack(fill="x", pady=3)
            ttk.Label(f, text=label, width=20, anchor="w").pack(side="left")
            ttk.Spinbox(f, from_=from_, to=to, increment=step,
                        textvariable=var, width=width).pack(side="left")

        ttk.Label(parent, text="Identity", font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
        lbl_entry("Nickname:", self._nickname)
        lbl_entry("Notes:", self._notes, width=40)

        f = ttk.Frame(parent)
        f.pack(fill="x", pady=3)
        ttk.Label(f, text="Serial:", width=20, anchor="w").pack(side="left")
        ttk.Label(f, text=self.result.serial, foreground="#888888").pack(side="left")

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(10, 4))
        ttk.Label(parent, text="Role & Profile", font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
        lbl_combo("Profile:", self._profile, PROFILES)

        f = ttk.Frame(parent)
        f.pack(fill="x", pady=3)
        ttk.Label(f, text="Is Lead Device:", width=20, anchor="w").pack(side="left")
        ttk.Checkbutton(f, variable=self._role_is_lead).pack(side="left")
        ttk.Label(f, text="(only one device may be lead)",
                  foreground="#888888").pack(side="left", padx=(6, 0))

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(10, 4))
        ttk.Label(parent, text="Capture & Scan", font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
        lbl_combo("Capture Backend:", self._backend, BACKENDS, width=12)
        lbl_spin("Scan Interval (ms):", self._scan_ms, 200, 5000, 100)

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(10, 4))
        ttk.Label(parent, text="Public Mode", font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
        f = ttk.Frame(parent)
        f.pack(fill="x", pady=3)
        ttk.Label(f, text="Revive Count:", width=20, anchor="w").pack(side="left")
        ttk.Spinbox(f, from_=0, to=99, textvariable=self._revive_count, width=6).pack(side="left")
        ttk.Label(f, text="(0 = disabled; resets to this value on app restart)",
                  foreground="#888888").pack(side="left", padx=(8, 0))

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(10, 4))
        ttk.Label(parent, text="Setup Tools", font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
        tools_row = ttk.Frame(parent)
        tools_row.pack(anchor="w", pady=4)
        ttk.Button(tools_row, text="Open Detector Tool", command=self._open_capture_tool).pack(side="left")

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(10, 4))
        ttk.Label(parent, text="Danger Zone", font=("TkDefaultFont", 9, "bold"),
                  foreground="#cc0000").pack(anchor="w")
        ttk.Button(parent, text="Remove This Device...", command=self._remove_device).pack(anchor="w", pady=4)

    def _build_timers_tab(self, parent: ttk.Frame) -> None:
        f = ttk.Frame(parent)
        f.pack(fill="x", pady=3)
        ttk.Label(f, text="Auto-Farm Reset:", width=22, anchor="w").pack(side="left")
        ttk.Checkbutton(f, text="Enabled", variable=self._auto_enabled).pack(side="left")
        ttk.Label(f, text="Interval (min):").pack(side="left", padx=(12, 4))
        ttk.Spinbox(f, from_=1, to=60, textvariable=self._auto_interval, width=6).pack(side="left")

        f = ttk.Frame(parent)
        f.pack(fill="x", pady=3)
        ttk.Label(f, text="End-Run Reset:", width=22, anchor="w").pack(side="left")
        ttk.Checkbutton(f, text="Enabled", variable=self._end_enabled).pack(side="left")
        ttk.Label(f, text="Interval (min):").pack(side="left", padx=(12, 4))
        ttk.Spinbox(f, from_=1, to=120, textvariable=self._end_interval, width=6).pack(side="left")

        f = ttk.Frame(parent)
        f.pack(fill="x", pady=3)
        ttk.Label(f, text="Cascade Reset:", width=22, anchor="w").pack(side="left")
        ttk.Checkbutton(f, text="Enabled", variable=self._cascade_enabled).pack(side="left")
        ttk.Label(f, text="Delay after lead (s):").pack(side="left", padx=(12, 4))
        ttk.Spinbox(f, from_=0, to=600, textvariable=self._cascade_delay, width=6).pack(side="left")
        ttk.Label(parent,
                  text="Only takes effect on the lead device — how long support devices\n"
                       "wait after the lead's end-run before firing their own.",
                  foreground="#888888", justify="left").pack(anchor="w", pady=(4, 0))

    def _build_actions_tab(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="On Death (Public Mode)", font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
        ttk.Checkbutton(parent, text="Turn off auto-farm on death",
                        variable=self._disable_auto_on_death).pack(anchor="w", pady=2)
        ttk.Checkbutton(parent, text="Save a screenshot on death",
                        variable=self._save_screenshot_on_death).pack(anchor="w", pady=2)
        ttk.Checkbutton(parent, text="Revive when available",
                        variable=self._revive_enabled).pack(anchor="w", pady=2)

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(10, 4))
        self._eaten_by_header = ttk.Label(parent, text="Eaten-By Detection (Lead Only, Private Mode)",
                                           font=("TkDefaultFont", 9, "bold"))
        self._eaten_by_header.pack(anchor="w")

        self._eaten_by_row1 = ttk.Frame(parent)
        ttk.Checkbutton(self._eaten_by_row1, text="Check who ate the lead on death",
                        variable=self._eaten_by_enabled).pack(anchor="w")

        self._eaten_by_row2 = ttk.Frame(parent)
        ttk.Checkbutton(self._eaten_by_row2, text="Trigger that support device's end-run when found",
                        variable=self._eaten_by_trigger).pack(anchor="w")

        self._eaten_by_hidden_note = ttk.Label(
            parent, text="(only applies to the lead device — check \"Is Lead Device\" on the General tab)",
            foreground="#888888")

    def _build_health_tab(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Protective Health Responses",
                  font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
        ttk.Checkbutton(parent, text="Sleep this device when battery is critically low",
                        variable=self._battery_protection).pack(anchor="w", pady=2)
        ttk.Checkbutton(parent, text="Pause this device when temperature is critically high",
                        variable=self._temp_protection).pack(anchor="w", pady=2)
        ttk.Label(parent,
                  text="Battery/temperature stats are always shown regardless of these settings —\n"
                       "turning a protection off only skips the automatic sleep/pause action.\n"
                       "Disabling temperature protection risks device damage; use with caution.",
                  foreground="#888888", justify="left").pack(anchor="w", pady=(8, 0))

    def _build_detectors_tab(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Detectors for this device's profile",
                  font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
        ttk.Label(parent,
                  text="Unchecking a detector skips it for this device only — the profile still\n"
                       "requires it for other devices. Disabling a detector the state machine\n"
                       "depends on (e.g. death_screen) can prevent correct state resolution.",
                  foreground="#888888", justify="left").pack(anchor="w", pady=(0, 8))
        self._detector_frame = ttk.Frame(parent)
        self._detector_frame.pack(fill="both", expand=True)
        self._rebuild_detector_checklist()

    # ------------------------------------------------------------------
    # Live reactivity
    # ------------------------------------------------------------------

    def _update_role_dependent_rows(self) -> None:
        """Show/hide the lead-only eaten-by rows based on the role checkbox (Phase 8 requirement)."""
        if self._role_is_lead.get():
            self._eaten_by_hidden_note.pack_forget()
            self._eaten_by_row1.pack(anchor="w", pady=2)
            self._eaten_by_row2.pack(anchor="w", pady=2)
        else:
            self._eaten_by_row1.pack_forget()
            self._eaten_by_row2.pack_forget()
            self._eaten_by_hidden_note.pack(anchor="w", pady=2)

    def _rebuild_detector_checklist(self) -> None:
        """Repopulate the Detectors tab from the currently-selected profile's detectors_required."""
        for widget in self._detector_frame.winfo_children():
            widget.destroy()
        self._detector_vars.clear()

        try:
            required = load_profile(self._profile.get()).detectors_required
        except FileNotFoundError:
            required = []

        if not required:
            ttk.Label(self._detector_frame, text="(no detectors required by this profile)",
                      foreground="#888888").pack(anchor="w", pady=4)
            return

        for name in required:
            var = tk.BooleanVar(value=name not in self._initial_disabled_detectors)
            self._detector_vars[name] = var
            ttk.Checkbutton(self._detector_frame, text=name, variable=var).pack(anchor="w", pady=1)

    # ------------------------------------------------------------------
    # Save / Presets
    # ------------------------------------------------------------------

    def _build_result(self) -> DeviceConfig:
        """
        Assemble a DeviceConfig from the dialog's current widget state,
        without saving or closing. Shared by _save() and the preset buttons
        so "current state" means the same thing in both places.
        """
        new_role = ROLE_LEAD if self._role_is_lead.get() else ROLE_SUPPORT
        disabled_detectors = [name for name, var in self._detector_vars.items() if not var.get()]

        return dataclasses.replace(
            self.result,
            nickname=self._nickname.get().strip(),
            role=new_role,
            profile=self._profile.get(),
            capture_backend=self._backend.get(),
            scan_interval_ms=self._scan_ms.get(),
            timers=dataclasses.replace(
                self.result.timers,
                auto_farm_reset_enabled=self._auto_enabled.get(),
                auto_farm_reset_interval_min=self._auto_interval.get(),
                end_run_reset_enabled=self._end_enabled.get(),
                end_run_reset_interval_min=self._end_interval.get(),
                cascade_reset_enabled=self._cascade_enabled.get(),
                cascade_reset_delay_after_lead_s=self._cascade_delay.get(),
            ),
            death_behavior=dataclasses.replace(
                self.result.death_behavior,
                disable_auto_on_death=self._disable_auto_on_death.get(),
                save_screenshot_on_death=self._save_screenshot_on_death.get(),
                revive_enabled=self._revive_enabled.get(),
                eaten_by_detection_enabled=self._eaten_by_enabled.get(),
                eaten_by_detection_trigger_support_end_run=self._eaten_by_trigger.get(),
            ),
            health_response=dataclasses.replace(
                self.result.health_response,
                battery_protection_enabled=self._battery_protection.get(),
                temp_protection_enabled=self._temp_protection.get(),
            ),
            disabled_detectors=disabled_detectors,
            revive_count=self._revive_count.get(),
            notes=self._notes.get().strip(),
        )

    def _apply_to_widgets(self, cfg: DeviceConfig) -> None:
        """Push a DeviceConfig's behavior fields back into the dialog's widgets (used after Load Preset)."""
        self._auto_enabled.set(cfg.timers.auto_farm_reset_enabled)
        self._auto_interval.set(cfg.timers.auto_farm_reset_interval_min)
        self._end_enabled.set(cfg.timers.end_run_reset_enabled)
        self._end_interval.set(cfg.timers.end_run_reset_interval_min)
        self._cascade_enabled.set(cfg.timers.cascade_reset_enabled)
        self._cascade_delay.set(cfg.timers.cascade_reset_delay_after_lead_s)

        self._disable_auto_on_death.set(cfg.death_behavior.disable_auto_on_death)
        self._save_screenshot_on_death.set(cfg.death_behavior.save_screenshot_on_death)
        self._revive_enabled.set(cfg.death_behavior.revive_enabled)
        self._eaten_by_enabled.set(cfg.death_behavior.eaten_by_detection_enabled)
        self._eaten_by_trigger.set(cfg.death_behavior.eaten_by_detection_trigger_support_end_run)

        self._battery_protection.set(cfg.health_response.battery_protection_enabled)
        self._temp_protection.set(cfg.health_response.temp_protection_enabled)

        disabled_set = set(cfg.disabled_detectors)
        for name, var in self._detector_vars.items():
            var.set(name not in disabled_set)

    def _save_as_preset(self) -> None:
        name = simpledialog.askstring("Save as Preset", "Preset name:", parent=self.top)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        if name in presets_mod.list_preset_names():
            if not messagebox.askyesno(
                "Overwrite Preset",
                f"A preset named '{name}' already exists. Overwrite it?",
                parent=self.top,
            ):
                return
        presets_mod.save_preset(name, self._build_result())
        messagebox.showinfo("Preset Saved", f"Saved current settings as preset '{name}'.", parent=self.top)

    def _load_preset(self) -> None:
        names = presets_mod.list_preset_names()
        if not names:
            messagebox.showinfo("No Presets", "No behavior presets have been saved yet.", parent=self.top)
            return
        chosen = _PresetPickerDialog(self.top, names).result
        if not chosen:
            return
        preset = presets_mod.load_preset(chosen)
        merged = presets_mod.apply_preset(self._build_result(), preset)
        self._apply_to_widgets(merged)

    def _save(self) -> None:
        new_role = ROLE_LEAD if self._role_is_lead.get() else ROLE_SUPPORT

        # Enforce one-lead rule
        if new_role == ROLE_LEAD:
            other_leads = [
                d for d in self.all_devices
                if d.role == ROLE_LEAD and d.serial != self.result.serial
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
                        d.role = ROLE_SUPPORT

        self.result = self._build_result()
        self.saved = True
        self.top.destroy()

    def _remove_device(self) -> None:
        """
        Confirm and flag this device for removal. Does NOT perform the actual
        deletion (stopping the worker, deleting assets, rewriting devices.json)
        here — app.py does that, the same handoff pattern as self.saved.
        """
        name = self.result.nickname or self.result.serial
        if not messagebox.askyesno(
            "Remove Device",
            f"This will permanently remove {name} and delete all its captured "
            f"detector images. This cannot be undone. Are you sure?",
            parent=self.top,
        ):
            return
        self.deleted = True
        self.top.destroy()

    def _open_capture_tool(self) -> None:
        """Launch the Detector Tool for this device."""
        from tools.image_capture_tool import ImageCaptureTool
        ImageCaptureTool(
            self.top,
            device_cfg=self.result,
            all_device_cfgs=self.all_devices,
        )


class _PresetPickerDialog:
    """Minimal modal: pick one preset name from a list. .result is the chosen name, or None if cancelled."""

    def __init__(self, parent, names: List[str]):
        self.result: Optional[str] = None

        self.top = tk.Toplevel(parent)
        self.top.title("Load Preset")
        self.top.grab_set()
        self.top.resizable(False, False)

        outer = ttk.Frame(self.top, padding=14)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Choose a preset to load:").pack(anchor="w", pady=(0, 6))

        self._choice = tk.StringVar(value=names[0])
        ttk.Combobox(outer, textvariable=self._choice, values=names,
                     state="readonly", width=30).pack(fill="x")

        btn_row = ttk.Frame(outer)
        btn_row.pack(anchor="e", pady=(10, 0))
        ttk.Button(btn_row, text="Load", command=self._ok).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Cancel", command=self.top.destroy).pack(side="left")

        parent.wait_window(self.top)

    def _ok(self) -> None:
        self.result = self._choice.get()
        self.top.destroy()
