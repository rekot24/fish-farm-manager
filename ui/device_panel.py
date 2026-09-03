"""
ui/device_panel.py

DevicePanel — one row in the device list for a single device.

Shows: lead star, nickname, role, state, battery %, temperature,
       auto-reset countdown, end-run countdown, and action buttons.
Updated every POLL_INTERVAL_MS by App._poll_status().
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from config.constants import ROLE_LEAD, ROLE_SUPPORT


def _fmt_countdown(seconds: float) -> str:
    """Format a countdown in seconds as MM:SS."""
    s = max(0, int(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def _state_color(state: str) -> str:
    """Map a state string to a display color."""
    return {
        "IN_RUN":       "#00c060",
        "DEAD":         "#e05050",
        "LOBBY":        "#e0a030",
        "LOADING":      "#8888cc",
        "JOINING":      "#8888cc",
        "CRASHED":      "#ff2020",
        "BATTERY_SLEEP":"#888888",
        "TEMP_PAUSE":   "#e06020",
        "ADB_LOST":     "#ff2020",
        "STOPPED":      "#888888",
    }.get(state, "#aaaaaa")


class DevicePanel(ttk.Frame):
    """
    A self-contained row widget for one device.
    Parent (App) calls update() on each poll tick.
    """

    def __init__(
        self,
        parent,
        status: dict,
        on_toggle: Callable,
        on_settings: Callable,
        on_end_run: Callable,
    ):
        super().__init__(parent, relief="groove", borderwidth=1, padding=(8, 6))
        self._on_toggle = on_toggle
        self._on_settings = on_settings
        self._on_end_run = on_end_run

        self.columnconfigure(1, weight=1)

        # ---- Row 1: lead star, name, role, state badge ----
        row1 = ttk.Frame(self)
        row1.grid(row=0, column=0, columnspan=3, sticky="ew")
        row1.columnconfigure(2, weight=1)

        self._lbl_lead = ttk.Label(row1, text="", width=2, font=("TkDefaultFont", 11))
        self._lbl_lead.grid(row=0, column=0)

        self._lbl_name = ttk.Label(row1, text="", font=("TkDefaultFont", 10, "bold"))
        self._lbl_name.grid(row=0, column=1, padx=(4, 8), sticky="w")

        self._lbl_role = ttk.Label(row1, text="", foreground="#888888")
        self._lbl_role.grid(row=0, column=2, sticky="w")

        self._lbl_state = tk.Label(
            row1, text="", fg="white", bg="#888888",
            font=("TkDefaultFont", 9, "bold"), padx=6, pady=1
        )
        self._lbl_state.grid(row=0, column=3, padx=(8, 0))

        self._lbl_health = ttk.Label(row1, text="")
        self._lbl_health.grid(row=0, column=4, padx=(12, 0))

        # ---- Row 2: timers ----
        row2 = ttk.Frame(self)
        row2.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(3, 0))

        ttk.Label(row2, text="Auto reset:", foreground="#888888").grid(row=0, column=0, sticky="w")
        self._lbl_auto_timer = ttk.Label(row2, text="--:--", width=6)
        self._lbl_auto_timer.grid(row=0, column=1, sticky="w", padx=(4, 20))

        ttk.Label(row2, text="End run:", foreground="#888888").grid(row=0, column=2, sticky="w")
        self._lbl_end_timer = ttk.Label(row2, text="--:--", width=6)
        self._lbl_end_timer.grid(row=0, column=3, sticky="w", padx=(4, 0))

        # ---- Row 3: action buttons ----
        row3 = ttk.Frame(self)
        row3.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))

        self._btn_toggle = ttk.Button(row3, text="Stop", command=on_toggle, width=8)
        self._btn_toggle.grid(row=0, column=0, padx=(0, 4))

        ttk.Button(row3, text="Settings", command=on_settings, width=8).grid(row=0, column=1, padx=(0, 4))
        ttk.Button(row3, text="End Run Now", command=on_end_run, width=12).grid(row=0, column=2)

        # Initial render
        self.update(status, timer_info=None)

    def update(self, status: dict, timer_info: Optional[dict]) -> None:
        """Refresh all labels from a fresh status dict."""
        role = status.get("role", ROLE_SUPPORT)
        nickname = status.get("nickname") or status.get("serial", "Unknown")[:12]
        profile = status.get("profile", "")
        role_label = "LEAD" if role == ROLE_LEAD else "SUPP"
        state = status.get("state", "UNKNOWN")
        running = status.get("running", False)
        battery = status.get("battery", -1)
        temp = status.get("temp", -1.0)

        self._lbl_lead.config(text="★" if role == ROLE_LEAD else "  ")
        self._lbl_name.config(text=nickname)
        self._lbl_role.config(text=f"{role_label}  {profile}")
        self._lbl_state.config(text=state, bg=_state_color(state))

        # Health display
        health_parts = []
        if battery >= 0:
            health_parts.append(f"🔋{battery}%")
        if temp >= 0:
            heat = "🔥" if temp > 45 else ""
            health_parts.append(f"{heat}{temp:.0f}°C")
        self._lbl_health.config(text="  ".join(health_parts))

        # Toggle button text
        self._btn_toggle.config(text="Stop" if running else "Start")

        # Timer countdowns
        if timer_info:
            auto_s = timer_info.get("auto_reset_remaining_s", 0)
            end_s = timer_info.get("end_run_remaining_s", 0)
            self._lbl_auto_timer.config(text=_fmt_countdown(auto_s))
            self._lbl_end_timer.config(text=_fmt_countdown(end_s))
        else:
            self._lbl_auto_timer.config(text="--:--")
            self._lbl_end_timer.config(text="--:--")
