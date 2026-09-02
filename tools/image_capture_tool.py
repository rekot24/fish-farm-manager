"""
tools/image_capture_tool.py

Detector setup and management tool. Two tabs:

  Tab 1 — Capture
    Guided wizard: select a detector, capture a live frame via ADB,
    drag to crop the region of interest, save as shared or device-specific,
    then test to verify confidence.

  Tab 2 — Manage
    Table of all detectors showing image scope, file status, and last test
    result per connected device. Run tests, promote/demote shared ↔ device-
    specific, delete images, jump back to Capture for recapture.
    Results are persisted to config/detector_results.json.
"""

from __future__ import annotations

import json
import threading
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import ttk, messagebox

import cv2
import numpy as np
from PIL import Image, ImageTk

from config.devices import DeviceConfig, DetectorConfig, load_devices, save_devices
from config.profiles import load_profile
from detection.template_bank import TemplateBank
from detection.detector import find_by_path, run_detector_by_name


# ---------------------------------------------------------------------------
# Detector instruction text
# ---------------------------------------------------------------------------

DETECTOR_INSTRUCTIONS = {
    "auto_button_on":    "Get the device into an active run with AUTO turned ON (button glowing/active).",
    "auto_button_off":   "Get the device into an active run with AUTO turned OFF (button dimmed/inactive).",
    "end_run_button":    "Get the device into an active run so the End Run button is visible.",
    "death_screen":      "Let the device die so the death screen is showing.",
    "in_run_indicator":  "Get the device into an active run (any indicator that confirms an active run).",
    "lobby_screen":      "Navigate the device to the game lobby (not in a tank).",
    "roblox_home_screen":"Close or crash Roblox so the Roblox home/launcher screen is showing.",
    "eaten_by_name":     "Get any device to a death screen where THIS device's character name is visible as the eater.",
    "revive_button":     "Get the device to a death screen in public mode where the revive button is visible.",
}

DEFAULT_INSTRUCTION = "Get the device to show this state, then press Ready — Capture Frame."

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = PROJECT_ROOT / "config" / "detector_results.json"


# ---------------------------------------------------------------------------
# Results persistence
# ---------------------------------------------------------------------------

def load_detector_results() -> Dict:
    """Load saved detector test results from config/detector_results.json."""
    if not RESULTS_PATH.exists():
        return {}
    try:
        with open(RESULTS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_detector_results(results: Dict) -> None:
    """Persist detector test results to config/detector_results.json."""
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)


def record_result(
    results: Dict,
    detector_name: str,
    device_serial: str,
    score: float,
    passed: bool,
    image_scope: str,
) -> None:
    """Write one test result into the results dict (in-place)."""
    if detector_name not in results:
        results[detector_name] = {}
    results[detector_name][device_serial] = {
        "score": round(score, 4),
        "passed": passed,
        "tested_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "image_scope": image_scope,
    }


# ---------------------------------------------------------------------------
# Main tool window
# ---------------------------------------------------------------------------

class ImageCaptureTool:
    """
    Two-tab detector management tool. Launched from device settings dialog.
    """

    def __init__(self, parent, device_cfg: DeviceConfig, all_device_cfgs: List[DeviceConfig]):
        self.parent = parent
        self.device_cfg = device_cfg           # the "primary" device (whose settings launched this)
        self.all_device_cfgs = all_device_cfgs # all configured devices (for Manage tab)
        self.bank = TemplateBank(project_root=PROJECT_ROOT)
        self.test_results = load_detector_results()

        # Build required detector list from profile + eaten_by_name special case
        try:
            profile = load_profile(device_cfg.profile)
            self.required_detectors = list(profile.detectors_required)
        except Exception:
            self.required_detectors = []

        if "eaten_by_name" not in self.required_detectors:
            self.required_detectors.append("eaten_by_name")

        self._build()

    # ------------------------------------------------------------------
    # Top-level window and tab structure
    # ------------------------------------------------------------------

    def _build(self) -> None:
        self.top = tk.Toplevel(self.parent)
        self.top.title(
            f"Detector Tool — {self.device_cfg.nickname or self.device_cfg.serial}"
        )
        self.top.geometry("1200x780")
        self.top.resizable(True, True)

        notebook = ttk.Notebook(self.top)
        notebook.pack(fill="both", expand=True, padx=6, pady=6)

        # Tab 1: Capture
        self._capture_frame_tab = ttk.Frame(notebook)
        notebook.add(self._capture_frame_tab, text="  Capture  ")
        self._build_capture_tab(self._capture_frame_tab)

        # Tab 2: Manage
        self._manage_frame_tab = ttk.Frame(notebook)
        notebook.add(self._manage_frame_tab, text="  Manage  ")
        self._build_manage_tab(self._manage_frame_tab)

        # Refresh manage tab whenever it becomes visible
        notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _on_tab_changed(self, event) -> None:
        nb = event.widget
        if nb.index(nb.select()) == 1:
            # Check if devices.json has new devices since the tool opened
            fresh = load_devices()
            fresh_serials = [d.serial for d in fresh]
            if fresh_serials != self._known_device_serials:
                self.all_device_cfgs = fresh
                self._build_device_checkboxes()
                # Rebuild tree columns to match new device list
                for widget in self._tree.master.winfo_children():
                    widget.destroy()
                self._build_manage_tree(self._tree.master)
                self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)
            self._refresh_manage_table()

    # ==================================================================
    # TAB 1 — CAPTURE
    # ==================================================================

    def _build_capture_tab(self, parent: ttk.Frame) -> None:
        """Build the guided capture wizard."""

        # State for this tab
        self._current_frame: Optional[np.ndarray] = None
        self._crop_start: Optional[Tuple] = None
        self._crop_rect: Optional[Tuple] = None
        self._canvas_scale = 1.0
        self._canvas_offset = (0, 0)
        self._photo: Optional[ImageTk.PhotoImage] = None
        self._rect_id = None
        self._selected_detector: Optional[str] = None

        paned = ttk.PanedWindow(parent, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=4, pady=4)

        # ---- Left: detector list ----
        left = ttk.Frame(paned, width=240)
        paned.add(left, weight=0)

        ttk.Label(
            left, text="Required Detectors",
            font=("TkDefaultFont", 10, "bold")
        ).pack(anchor="w", pady=(0, 6))

        list_frame = ttk.Frame(left)
        list_frame.pack(fill="both", expand=True)

        sb = ttk.Scrollbar(list_frame)
        sb.pack(side="right", fill="y")

        self._detector_list = tk.Listbox(
            list_frame, yscrollcommand=sb.set,
            selectmode="single", width=28, activestyle="none",
            font=("Consolas", 10),
        )
        self._detector_list.pack(side="left", fill="both", expand=True)
        sb.config(command=self._detector_list.yview)
        self._detector_list.bind("<<ListboxSelect>>", self._on_detector_select)

        # ---- Right: capture/crop area ----
        right = ttk.Frame(paned)
        paned.add(right, weight=1)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        self._lbl_instruction = ttk.Label(
            right,
            text="Select a detector from the list to begin.",
            wraplength=720, justify="left",
            font=("TkDefaultFont", 10),
        )
        self._lbl_instruction.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        btn_row = ttk.Frame(right)
        btn_row.grid(row=1, column=0, sticky="w", pady=(0, 4))

        self._btn_ready = ttk.Button(
            btn_row, text="Ready — Capture Frame",
            command=self._capture_frame_from_device, state="disabled"
        )
        self._btn_ready.pack(side="left", padx=(0, 6))

        self._btn_save = ttk.Button(
            btn_row, text="Save Crop",
            command=self._save_crop, state="disabled"
        )
        self._btn_save.pack(side="left", padx=(0, 6))

        self._btn_test_capture = ttk.Button(
            btn_row, text="Test Detection",
            command=lambda: self._run_test_single(self._selected_detector, self.device_cfg),
            state="disabled",
        )
        self._btn_test_capture.pack(side="left", padx=(0, 6))

        self._lbl_capture_result = ttk.Label(btn_row, text="", font=("TkDefaultFont", 10))
        self._lbl_capture_result.pack(side="left", padx=(10, 0))

        # Canvas
        canvas_wrap = ttk.Frame(right, relief="sunken", borderwidth=1)
        canvas_wrap.grid(row=2, column=0, sticky="nsew")
        canvas_wrap.rowconfigure(0, weight=1)
        canvas_wrap.columnconfigure(0, weight=1)

        self._canvas = tk.Canvas(canvas_wrap, bg="#1a1a1a", cursor="crosshair")
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._canvas.bind("<ButtonPress-1>", self._on_mouse_down)
        self._canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_mouse_up)

        self._lbl_capture_status = ttk.Label(
            right, text="No frame captured.", foreground="#888888"
        )
        self._lbl_capture_status.grid(row=3, column=0, sticky="w", pady=(3, 0))

        self._populate_detector_list()

    # ---- Detector list helpers ----

    def _populate_detector_list(self) -> None:
        self._detector_list.delete(0, "end")
        for name in self.required_detectors:
            exists = self._image_exists(name, self.device_cfg)
            icon = "✓" if exists else "✗"
            self._detector_list.insert("end", f" {icon}  {name}")
            color = "#00aa44" if exists else "#cc2222"
            self._detector_list.itemconfig("end", foreground=color)

    def _image_exists(self, detector_name: str, dev: DeviceConfig) -> bool:
        if detector_name == "eaten_by_name":
            p = dev.eaten_by_name_image
            return bool(p) and (PROJECT_ROOT / p).exists()
        return self.bank.exists(detector_name, dev.serial, dev.device_image_overrides)

    def _get_image_scope(self, detector_name: str, dev: DeviceConfig) -> str:
        """Return 'device:{serial}', 'shared', or 'missing'."""
        if detector_name == "eaten_by_name":
            p = dev.eaten_by_name_image
            return f"device:{dev.serial}" if (p and (PROJECT_ROOT / p).exists()) else "missing"
        if not self.bank.exists(detector_name, dev.serial, dev.device_image_overrides):
            return "missing"
        if detector_name in dev.device_image_overrides:
            return f"device:{dev.serial}"
        return "shared"

    def _on_detector_select(self, event) -> None:
        sel = self._detector_list.curselection()
        if not sel:
            return
        name = self.required_detectors[sel[0]]
        self._selected_detector = name

        instruction = DETECTOR_INSTRUCTIONS.get(name, DEFAULT_INSTRUCTION)
        self._lbl_instruction.config(text=f"Detector: {name}\n\n{instruction}")
        self._btn_ready.config(state="normal")
        self._btn_save.config(state="disabled")
        self._lbl_capture_result.config(text="")

        exists = self._image_exists(name, self.device_cfg)
        self._btn_test_capture.config(state="normal" if exists else "disabled")
        self._clear_canvas()

    # ---- Frame capture ----

    def _capture_frame_from_device(self, device_cfg: Optional[DeviceConfig] = None) -> None:
        dev = device_cfg or self.device_cfg
        self._btn_ready.config(state="disabled")
        self._lbl_capture_status.config(text="Capturing frame...")
        self.top.update_idletasks()

        def do_capture():
            try:
                result = subprocess.run(
                    ["adb", "-s", dev.serial, "exec-out", "screencap", "-p"],
                    capture_output=True, timeout=10,
                )
                if result.returncode != 0 or not result.stdout:
                    self.top.after(0, lambda: self._capture_failed("ADB screencap returned no data"))
                    return
                arr = np.frombuffer(result.stdout, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is None:
                    self.top.after(0, lambda: self._capture_failed("Could not decode screenshot"))
                    return
                self.top.after(0, lambda: self._capture_success(frame))
            except subprocess.TimeoutExpired:
                self.top.after(0, lambda: self._capture_failed("ADB timed out"))
            except Exception as e:
                self.top.after(0, lambda: self._capture_failed(str(e)))

        threading.Thread(target=do_capture, daemon=True).start()

    def _capture_success(self, frame: np.ndarray) -> None:
        self._current_frame = frame
        self._crop_rect = None
        self._btn_ready.config(state="normal")
        self._btn_save.config(state="disabled")
        self._lbl_capture_result.config(text="")
        h, w = frame.shape[:2]
        self._lbl_capture_status.config(
            text=f"Frame captured: {w}×{h}. Drag to crop the target region."
        )
        self._display_frame(frame)

    def _capture_failed(self, reason: str) -> None:
        self._btn_ready.config(state="normal")
        self._lbl_capture_status.config(text=f"Capture failed: {reason}", foreground="red")

    # ---- Canvas display and crop ----

    def _display_frame(self, frame: np.ndarray) -> None:
        cw = self._canvas.winfo_width() or 860
        ch = self._canvas.winfo_height() or 520
        fh, fw = frame.shape[:2]
        scale = min(cw / fw, ch / fh, 1.0)
        nw, nh = int(fw * scale), int(fh * scale)
        self._canvas_scale = scale
        self._canvas_offset = ((cw - nw) // 2, (ch - nh) // 2)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb).resize((nw, nh), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(pil)
        self._canvas.delete("all")
        ox, oy = self._canvas_offset
        self._canvas.create_image(ox, oy, anchor="nw", image=self._photo)
        self._rect_id = None

    def _clear_canvas(self) -> None:
        self._canvas.delete("all")
        self._current_frame = None
        self._crop_rect = None
        self._photo = None

    def _canvas_to_image(self, cx: int, cy: int) -> Tuple[int, int]:
        ox, oy = self._canvas_offset
        ix = int((cx - ox) / self._canvas_scale)
        iy = int((cy - oy) / self._canvas_scale)
        if self._current_frame is not None:
            h, w = self._current_frame.shape[:2]
            ix = max(0, min(ix, w - 1))
            iy = max(0, min(iy, h - 1))
        return ix, iy

    def _on_mouse_down(self, event) -> None:
        if self._current_frame is None:
            return
        self._crop_start = (event.x, event.y)
        if self._rect_id:
            self._canvas.delete(self._rect_id)
            self._rect_id = None

    def _on_mouse_drag(self, event) -> None:
        if not self._crop_start or self._current_frame is None:
            return
        if self._rect_id:
            self._canvas.delete(self._rect_id)
        x0, y0 = self._crop_start
        self._rect_id = self._canvas.create_rectangle(
            x0, y0, event.x, event.y,
            outline="#00ff88", width=2, dash=(4, 2),
        )

    def _on_mouse_up(self, event) -> None:
        if not self._crop_start or self._current_frame is None:
            return
        x0, y0 = self._crop_start
        ix0, iy0 = self._canvas_to_image(min(x0, event.x), min(y0, event.y))
        ix1, iy1 = self._canvas_to_image(max(x0, event.x), max(y0, event.y))
        if ix1 - ix0 < 5 or iy1 - iy0 < 5:
            self._lbl_capture_status.config(text="Crop too small — drag a larger region.")
            return
        self._crop_rect = (ix0, iy0, ix1, iy1)
        self._lbl_capture_status.config(
            text=f"Crop: {ix1-ix0}×{iy1-iy0} at ({ix0},{iy0}). Click Save Crop to save."
        )
        self._btn_save.config(state="normal")

    # ---- Save crop ----

    def _save_crop(self) -> None:
        if self._current_frame is None or self._crop_rect is None or not self._selected_detector:
            return

        name = self._selected_detector
        ix0, iy0, ix1, iy1 = self._crop_rect
        crop = self._current_frame[iy0:iy1, ix0:ix1]

        if crop.size == 0:
            messagebox.showerror("Error", "Crop region is empty.", parent=self.top)
            return

        if name == "eaten_by_name":
            self._do_save_eaten_by(crop)
            return

        choice = _AskSaveScope(self.top, name).result
        if choice is None:
            return
        self._do_save(crop, name, device_specific=(choice == "device"))

    def _do_save(self, crop: np.ndarray, name: str, device_specific: bool) -> None:
        if device_specific:
            out_dir = PROJECT_ROOT / "assets" / "devices" / self.device_cfg.serial
        else:
            out_dir = PROJECT_ROOT / "assets" / "shared"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{name}.png"
        cv2.imwrite(str(out_path), crop)

        # Update devices.json
        devices = load_devices()
        for dev in devices:
            if dev.serial == self.device_cfg.serial:
                overrides = list(dev.device_image_overrides)
                if device_specific and name not in overrides:
                    overrides.append(name)
                elif not device_specific and name in overrides:
                    overrides.remove(name)
                dev.device_image_overrides = overrides
                if name not in dev.detectors:
                    dev.detectors[name] = DetectorConfig(
                        image=str(out_path.relative_to(PROJECT_ROOT)),
                        click_offset=[0, 0],
                    )
                else:
                    dev.detectors[name].image = str(out_path.relative_to(PROJECT_ROOT))
                    dev.detectors[name].click_offset = [0, 0]
                self.device_cfg = dev
                break
        save_devices(devices)

        # Invalidate cache
        if device_specific:
            self.bank.invalidate(name, self.device_cfg.serial)
        else:
            self.bank.invalidate(name, None)

        scope = f"device-specific ({self.device_cfg.nickname})" if device_specific else "shared"
        self._lbl_capture_status.config(
            text=f"Saved {name}.png as {scope}. Run Test Detection to verify."
        )
        self._btn_test_capture.config(state="normal")
        self._populate_detector_list()

    def _do_save_eaten_by(self, crop: np.ndarray) -> None:
        out_dir = PROJECT_ROOT / "assets" / "devices" / self.device_cfg.serial
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "eaten_by_name.png"
        cv2.imwrite(str(out_path), crop)

        devices = load_devices()
        for dev in devices:
            if dev.serial == self.device_cfg.serial:
                dev.eaten_by_name_image = str(out_path.relative_to(PROJECT_ROOT))
                self.device_cfg = dev
                break
        save_devices(devices)
        self.bank.invalidate_by_path(str(out_path))

        self._lbl_capture_status.config(
            text=f"Saved eaten_by_name for {self.device_cfg.nickname}. Run Test Detection to verify."
        )
        self._btn_test_capture.config(state="normal")
        self._populate_detector_list()

    # ==================================================================
    # TAB 2 — MANAGE
    # ==================================================================

    def _build_manage_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        # ---- Toolbar ----
        toolbar = ttk.Frame(parent)
        toolbar.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 2))

        ttk.Label(toolbar, text="Test on devices:").pack(side="left", padx=(0, 8))

        # Device checkbox container — rebuilt dynamically when device list changes
        self._device_checkbox_frame = ttk.Frame(toolbar)
        self._device_checkbox_frame.pack(side="left")
        self._device_vars: Dict[str, tk.BooleanVar] = {}
        self._known_device_serials: List[str] = []  # tracks last-known list for change detection
        self._build_device_checkboxes()

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Button(
            toolbar, text="▶  Run Tests on Selected",
            command=self._run_tests_selected,
        ).pack(side="left", padx=(0, 6))

        ttk.Button(
            toolbar, text="↺  Refresh",
            command=self._refresh_manage_table,
        ).pack(side="left")

        # ---- Main paned area: left = detector checklist, right = table ----
        paned = ttk.PanedWindow(parent, orient="horizontal")
        paned.grid(row=1, column=0, sticky="nsew", padx=4, pady=(2, 0))

        # Left: detector checklist
        left = ttk.Frame(paned, width=220)
        paned.add(left, weight=0)
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        # Check All / Uncheck All buttons
        chk_ctrl = ttk.Frame(left)
        chk_ctrl.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        ttk.Button(chk_ctrl, text="All",
                   command=self._check_all_detectors, width=5).pack(side="left", padx=(0, 4))
        ttk.Button(chk_ctrl, text="None",
                   command=self._uncheck_all_detectors, width=5).pack(side="left")

        det_list_frame = ttk.Frame(left)
        det_list_frame.grid(row=1, column=0, sticky="nsew")
        det_list_frame.rowconfigure(0, weight=1)
        det_list_frame.columnconfigure(0, weight=1)

        det_sb = ttk.Scrollbar(det_list_frame)
        det_sb.grid(row=0, column=1, sticky="ns")

        self._manage_det_list = tk.Listbox(
            det_list_frame, yscrollcommand=det_sb.set,
            selectmode="single", width=26, activestyle="none",
            font=("Consolas", 10),
        )
        self._manage_det_list.grid(row=0, column=0, sticky="nsew")
        det_sb.config(command=self._manage_det_list.yview)

        # Detector checkboxes dict: name -> BooleanVar
        self._detector_check_vars: Dict[str, tk.BooleanVar] = {}
        self._build_detector_checklist()

        # Right: results table
        right = ttk.Frame(paned)
        paned.add(right, weight=1)
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        self._build_manage_tree(right)

        # ---- Status bar ----
        self._lbl_manage_status = ttk.Label(
            parent, text="", foreground="#888888"
        )
        self._lbl_manage_status.grid(row=2, column=0, sticky="w", padx=4, pady=(0, 2))

        # ---- Action buttons panel ----
        action_frame = ttk.LabelFrame(parent, text="Selected Detector", padding=6)
        action_frame.grid(row=3, column=0, sticky="ew", padx=4, pady=(0, 4))

        self._btn_recapture = ttk.Button(
            action_frame, text="📷  Recapture",
            command=self._action_recapture, state="disabled",
        )
        self._btn_recapture.pack(side="left", padx=(0, 6))

        self._btn_toggle_scope = ttk.Button(
            action_frame, text="⇄  Toggle Shared/Device",
            command=self._action_toggle_scope, state="disabled",
        )
        self._btn_toggle_scope.pack(side="left", padx=(0, 6))

        self._btn_delete_image = ttk.Button(
            action_frame, text="🗑  Delete Image",
            command=self._action_delete_image, state="disabled",
        )
        self._btn_delete_image.pack(side="left", padx=(0, 6))

        self._lbl_selected = ttk.Label(
            action_frame, text="No detector selected.", foreground="#888888"
        )
        self._lbl_selected.pack(side="left", padx=(12, 0))

        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        self._refresh_manage_table()

    def _build_device_checkboxes(self) -> None:
        """Build or rebuild the device checkbox row from current all_device_cfgs."""
        for widget in self._device_checkbox_frame.winfo_children():
            widget.destroy()

        self._known_device_serials = [d.serial for d in self.all_device_cfgs]

        for dev in self.all_device_cfgs:
            # Preserve existing checked state if the device was already there
            if dev.serial not in self._device_vars:
                self._device_vars[dev.serial] = tk.BooleanVar(
                    value=(dev.serial == self.device_cfg.serial)
                )
            ttk.Checkbutton(
                self._device_checkbox_frame,
                text=dev.nickname or dev.serial[:8],
                variable=self._device_vars[dev.serial],
            ).pack(side="left", padx=(0, 6))

    def _build_detector_checklist(self) -> None:
        """Populate the detector checklist on the left of the Manage tab."""
        self._manage_det_list.delete(0, "end")
        self._detector_check_vars.clear()

        for name in self.required_detectors:
            var = tk.BooleanVar(value=True)
            self._detector_check_vars[name] = var
            self._manage_det_list.insert("end", f" ☑  {name}")
            self._manage_det_list.itemconfig("end", foreground="#333333")

        # Toggle checkbox state on click
        self._manage_det_list.bind("<ButtonRelease-1>", self._on_det_checklist_click)

    def _on_det_checklist_click(self, event) -> None:
        """Toggle the checkbox for the clicked detector row."""
        idx = self._manage_det_list.nearest(event.y)
        if idx < 0 or idx >= len(self.required_detectors):
            return
        name = self.required_detectors[idx]
        var = self._detector_check_vars[name]
        var.set(not var.get())
        self._update_det_checklist_display()

    def _update_det_checklist_display(self) -> None:
        """Redraw checklist icons to match current checkbox states."""
        for idx, name in enumerate(self.required_detectors):
            checked = self._detector_check_vars[name].get()
            icon = "☑" if checked else "☐"
            color = "#333333" if checked else "#888888"
            self._manage_det_list.delete(idx)
            self._manage_det_list.insert(idx, f" {icon}  {name}")
            self._manage_det_list.itemconfig(idx, foreground=color)

    def _check_all_detectors(self) -> None:
        for var in self._detector_check_vars.values():
            var.set(True)
        self._update_det_checklist_display()

    def _uncheck_all_detectors(self) -> None:
        for var in self._detector_check_vars.values():
            var.set(False)
        self._update_det_checklist_display()

    def _build_manage_tree(self, parent: ttk.Frame) -> None:
        """Build the results treeview. Called once; columns rebuilt if devices change."""
        fixed_cols = ("detector", "scope", "file")
        device_cols = tuple(f"dev_{d.serial}" for d in self.all_device_cfgs)
        action_col = ("actions",)
        all_cols = fixed_cols + device_cols + action_col

        self._tree = ttk.Treeview(
            parent,
            columns=all_cols,
            show="headings",
            selectmode="browse",
        )

        self._tree.heading("detector", text="Detector")
        self._tree.heading("scope",    text="Scope")
        self._tree.heading("file",     text="File")
        self._tree.column("detector", width=160, minwidth=120, anchor="w")
        self._tree.column("scope",    width=160, minwidth=120, anchor="w")
        self._tree.column("file",     width=50,  minwidth=40,  anchor="center")

        for dev in self.all_device_cfgs:
            col = f"dev_{dev.serial}"
            label = dev.nickname or dev.serial[:8]
            self._tree.heading(col, text=label)
            self._tree.column(col, width=130, minwidth=100, anchor="center")

        self._tree.heading("actions", text="Actions")
        self._tree.column("actions", width=180, minwidth=160, anchor="w")

        vsb = ttk.Scrollbar(parent, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self._tree.tag_configure("ok",       foreground="#00aa44")
        self._tree.tag_configure("missing",  foreground="#cc2222")
        self._tree.tag_configure("untested", foreground="#aa8800")
        self._tree.tag_configure("failed",   foreground="#cc2222")

    def _refresh_manage_table(self) -> None:
        """Rebuild the manage table from current disk state and saved results."""
        fresh_devices = load_devices()
        self.all_device_cfgs = fresh_devices
        for dev in fresh_devices:
            if dev.serial == self.device_cfg.serial:
                self.device_cfg = dev
                break

        self._tree.delete(*self._tree.get_children())

        for det_name in self.required_detectors:
            scope = self._get_image_scope(det_name, self.device_cfg)
            file_ok = "✓" if scope != "missing" else "✗"

            if scope == "missing":
                scope_text = "— missing —"
            elif scope == "shared":
                scope_text = "Shared"
            else:
                serial = scope.split(":", 1)[1]
                nick = next(
                    (d.nickname or d.serial[:8] for d in self.all_device_cfgs if d.serial == serial),
                    serial[:8],
                )
                scope_text = f"Device: {nick}"

            row_values = [det_name, scope_text, file_ok]
            row_tag = "ok" if file_ok == "✓" else "missing"

            for dev in self.all_device_cfgs:
                det_results = self.test_results.get(det_name, {})
                dev_result = det_results.get(dev.serial)
                if dev_result is None:
                    cell = "—"
                    if row_tag == "ok":
                        row_tag = "untested"
                elif dev_result["passed"]:
                    pct = int(dev_result["score"] * 100)
                    ts = dev_result["tested_at"][11:16]
                    cell = f"✓ {pct}%  {ts}"
                else:
                    pct = int(dev_result["score"] * 100)
                    cell = f"✗ {pct}%"
                    row_tag = "failed"
                row_values.append(cell)

            row_values.append("Select row to act")

            self._tree.insert(
                "", "end",
                iid=det_name,
                values=row_values,
                tags=(row_tag,),
            )

        self._lbl_manage_status.config(
            text=f"Showing {len(self.required_detectors)} detectors · "
                 f"{len(self.all_device_cfgs)} devices · "
                 f"Last refresh: {datetime.now().strftime('%H:%M:%S')}"
        )

    def _on_tree_select(self, event) -> None:
        sel = self._tree.selection()
        if not sel:
            self._btn_recapture.config(state="disabled")
            self._btn_toggle_scope.config(state="disabled")
            self._btn_delete_image.config(state="disabled")
            self._lbl_selected.config(text="No detector selected.")
            return

        det_name = sel[0]
        scope = self._get_image_scope(det_name, self.device_cfg)
        exists = scope != "missing"

        self._btn_recapture.config(state="normal")
        self._btn_toggle_scope.config(state="normal" if exists else "disabled")
        self._btn_delete_image.config(state="normal" if exists else "disabled")

        scope_label = "shared" if scope == "shared" else (
            f"device-specific ({self.device_cfg.nickname})" if exists else "missing"
        )
        self._lbl_selected.config(
            text=f"{det_name}  ·  {scope_label}",
            foreground="#333333",
        )

    # ---- Test runner ----

    def _run_tests_selected(self) -> None:
        """
        Run detection tests for checked detectors on checked devices.
        Each device gets one screenshot capture; only the checked detectors
        are tested against it so you control exactly what's being evaluated.
        """
        selected_serials = [s for s, v in self._device_vars.items() if v.get()]
        if not selected_serials:
            messagebox.showinfo(
                "No Devices",
                "Check at least one device to test against.",
                parent=self.top,
            )
            return

        selected_detectors = [
            name for name in self.required_detectors
            if self._detector_check_vars.get(name, tk.BooleanVar(value=False)).get()
        ]
        if not selected_detectors:
            messagebox.showinfo(
                "No Detectors",
                "Check at least one detector to test.",
                parent=self.top,
            )
            return

        selected_devs = [d for d in self.all_device_cfgs if d.serial in selected_serials]
        n_tests = len(selected_detectors) * len(selected_devs)
        self._lbl_manage_status.config(
            text=f"Running {n_tests} test(s) "
                 f"({len(selected_detectors)} detector(s) × {len(selected_devs)} device(s))..."
        )
        self.top.update_idletasks()

        def do_tests():
            for dev in selected_devs:
                # One screenshot capture per device
                try:
                    result = subprocess.run(
                        ["adb", "-s", dev.serial, "exec-out", "screencap", "-p"],
                        capture_output=True, timeout=15,
                    )
                    if result.returncode != 0 or not result.stdout:
                        self.top.after(0, lambda d=dev: self._lbl_manage_status.config(
                            text=f"Capture failed for {d.nickname or d.serial}"
                        ))
                        continue
                    arr = np.frombuffer(result.stdout, dtype=np.uint8)
                    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    if frame is None:
                        continue
                except Exception as e:
                    self.top.after(0, lambda e=e: self._lbl_manage_status.config(
                        text=f"Error capturing {dev.nickname or dev.serial}: {e}"
                    ))
                    continue

                # Only test the checked detectors
                for det_name in selected_detectors:
                    if det_name == "eaten_by_name":
                        path = dev.eaten_by_name_image
                        if not path or not (PROJECT_ROOT / path).exists():
                            continue
                        detect_result = find_by_path(
                            frame_bgr=frame,
                            image_path=str(PROJECT_ROOT / path),
                            bank=self.bank,
                            detector_name="eaten_by_name",
                        )
                    else:
                        if not self.bank.exists(det_name, dev.serial, dev.device_image_overrides):
                            continue
                        detect_result = run_detector_by_name(
                            detector_name=det_name,
                            frame_bgr=frame,
                            device_serial=dev.serial,
                            device_overrides=dev.device_image_overrides,
                            bank=self.bank,
                        )

                    scope = self._get_image_scope(det_name, dev)
                    record_result(
                        self.test_results,
                        det_name,
                        dev.serial,
                        score=detect_result.score or 0.0,
                        passed=detect_result.found,
                        image_scope=scope,
                    )

            save_detector_results(self.test_results)
            self.top.after(0, self._refresh_manage_table)

        threading.Thread(target=do_tests, daemon=True).start()

    def _run_test_single(
        self,
        detector_name: Optional[str],
        dev: DeviceConfig,
    ) -> None:
        """Run a single detector test from the Capture tab."""
        if not detector_name:
            return

        self._lbl_capture_result.config(text="Testing...", foreground="#888888")
        self._btn_test_capture.config(state="disabled")
        self.top.update_idletasks()

        def do_test():
            try:
                result = subprocess.run(
                    ["adb", "-s", dev.serial, "exec-out", "screencap", "-p"],
                    capture_output=True, timeout=10,
                )
                if result.returncode != 0 or not result.stdout:
                    self.top.after(0, lambda: self._single_test_done(None, "Capture failed"))
                    return
                arr = np.frombuffer(result.stdout, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is None:
                    self.top.after(0, lambda: self._single_test_done(None, "Decode failed"))
                    return
            except Exception as e:
                self.top.after(0, lambda: self._single_test_done(None, str(e)))
                return

            try:
                if detector_name == "eaten_by_name":
                    path = dev.eaten_by_name_image
                    if not path:
                        self.top.after(0, lambda: self._single_test_done(None, "No image saved"))
                        return
                    detect_result = find_by_path(
                        frame_bgr=frame,
                        image_path=str(PROJECT_ROOT / path),
                        bank=self.bank,
                        detector_name="eaten_by_name",
                    )
                else:
                    detect_result = run_detector_by_name(
                        detector_name=detector_name,
                        frame_bgr=frame,
                        device_serial=dev.serial,
                        device_overrides=dev.device_image_overrides,
                        bank=self.bank,
                    )

                scope = self._get_image_scope(detector_name, dev)
                record_result(
                    self.test_results,
                    detector_name,
                    dev.serial,
                    score=detect_result.score or 0.0,
                    passed=detect_result.found,
                    image_scope=scope,
                )
                save_detector_results(self.test_results)
                self.top.after(0, lambda r=detect_result, f=frame: self._single_test_done(r, None, f))

            except Exception as e:
                self.top.after(0, lambda: self._single_test_done(None, str(e)))

        threading.Thread(target=do_test, daemon=True).start()

    def _single_test_done(
        self,
        result,
        error: Optional[str],
        frame: Optional[np.ndarray] = None,
    ) -> None:
        self._btn_test_capture.config(state="normal")
        if error:
            self._lbl_capture_result.config(text=f"Error: {error}", foreground="#cc2222")
            return
        if result.found:
            pct = int((result.score or 0) * 100)
            self._lbl_capture_result.config(
                text=f"✓ FOUND  {pct}%  center={result.center}",
                foreground="#00cc55",
            )
            if frame is not None:
                annotated = frame.copy()
                if result.bbox:
                    x, y, w, h = result.bbox
                    cv2.rectangle(annotated, (x, y), (x+w, y+h), (0, 255, 128), 2)
                    if result.center:
                        cv2.circle(annotated, result.center, 6, (0, 255, 128), -1)
                self._display_frame(annotated)
        else:
            pct = int((result.score or 0) * 100)
            self._lbl_capture_result.config(
                text=f"✗ NOT FOUND  best score={pct}%  (threshold ~82%)",
                foreground="#cc2222",
            )
            if frame is not None:
                self._display_frame(frame)
        self._populate_detector_list()

    # ---- Row action handlers ----

    def _action_recapture(self) -> None:
        """Switch to Capture tab with the selected detector pre-selected."""
        sel = self._tree.selection()
        if not sel:
            return
        det_name = sel[0]

        # Find and switch to the Capture tab
        nb = self.top.winfo_children()[0]   # the Notebook
        nb.select(0)

        # Select the detector in the listbox
        if det_name in self.required_detectors:
            idx = self.required_detectors.index(det_name)
            self._detector_list.selection_clear(0, "end")
            self._detector_list.selection_set(idx)
            self._detector_list.see(idx)
            self._on_detector_select(None)

    def _action_toggle_scope(self) -> None:
        """Toggle selected detector between shared and device-specific."""
        sel = self._tree.selection()
        if not sel:
            return
        det_name = sel[0]

        if det_name == "eaten_by_name":
            messagebox.showinfo(
                "Not Applicable",
                "eaten_by_name is always device-specific.",
                parent=self.top,
            )
            return

        current_scope = self._get_image_scope(det_name, self.device_cfg)
        if current_scope == "missing":
            messagebox.showinfo("No Image", "No image exists to toggle.", parent=self.top)
            return

        is_device_specific = det_name in self.device_cfg.device_image_overrides

        if is_device_specific:
            # Promote to shared: copy device image → shared dir
            src = PROJECT_ROOT / "assets" / "devices" / self.device_cfg.serial / f"{det_name}.png"
            dst_dir = PROJECT_ROOT / "assets" / "shared"
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / f"{det_name}.png"

            if dst.exists():
                if not messagebox.askyesno(
                    "Overwrite Shared?",
                    f"A shared image for '{det_name}' already exists.\nOverwrite it?",
                    parent=self.top,
                ):
                    return

            import shutil
            shutil.copy2(str(src), str(dst))

            # Update override list
            devices = load_devices()
            for dev in devices:
                if dev.serial == self.device_cfg.serial:
                    overrides = list(dev.device_image_overrides)
                    if det_name in overrides:
                        overrides.remove(det_name)
                    dev.device_image_overrides = overrides
                    self.device_cfg = dev
                    break
            save_devices(devices)

            self.bank.invalidate(det_name, self.device_cfg.serial)
            self.bank.invalidate(det_name, None)
            self._lbl_manage_status.config(text=f"'{det_name}' promoted to shared.")

        else:
            # Demote to device-specific: copy shared → device dir
            src = PROJECT_ROOT / "assets" / "shared" / f"{det_name}.png"
            dst_dir = PROJECT_ROOT / "assets" / "devices" / self.device_cfg.serial
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / f"{det_name}.png"

            import shutil
            shutil.copy2(str(src), str(dst))

            # Update override list
            devices = load_devices()
            for dev in devices:
                if dev.serial == self.device_cfg.serial:
                    overrides = list(dev.device_image_overrides)
                    if det_name not in overrides:
                        overrides.append(det_name)
                    dev.device_image_overrides = overrides
                    self.device_cfg = dev
                    break
            save_devices(devices)

            self.bank.invalidate(det_name, self.device_cfg.serial)
            self.bank.invalidate(det_name, None)
            self._lbl_manage_status.config(
                text=f"'{det_name}' demoted to device-specific for {self.device_cfg.nickname}."
            )

        self._refresh_manage_table()
        self._populate_detector_list()

    def _action_delete_image(self) -> None:
        """Delete the image for the selected detector."""
        sel = self._tree.selection()
        if not sel:
            return
        det_name = sel[0]

        if not messagebox.askyesno(
            "Delete Image",
            f"Delete the image for '{det_name}'?\nThis cannot be undone.",
            parent=self.top,
        ):
            return

        if det_name == "eaten_by_name":
            path_str = self.device_cfg.eaten_by_name_image
            if path_str:
                p = PROJECT_ROOT / path_str
                if p.exists():
                    p.unlink()
            devices = load_devices()
            for dev in devices:
                if dev.serial == self.device_cfg.serial:
                    dev.eaten_by_name_image = ""
                    self.device_cfg = dev
                    break
            save_devices(devices)
        else:
            is_device_specific = det_name in self.device_cfg.device_image_overrides
            if is_device_specific:
                p = PROJECT_ROOT / "assets" / "devices" / self.device_cfg.serial / f"{det_name}.png"
            else:
                p = PROJECT_ROOT / "assets" / "shared" / f"{det_name}.png"

            if p.exists():
                p.unlink()

            # Remove from overrides if device-specific
            if is_device_specific:
                devices = load_devices()
                for dev in devices:
                    if dev.serial == self.device_cfg.serial:
                        overrides = list(dev.device_image_overrides)
                        if det_name in overrides:
                            overrides.remove(det_name)
                        dev.device_image_overrides = overrides
                        self.device_cfg = dev
                        break
                save_devices(devices)

            self.bank.invalidate(det_name, self.device_cfg.serial if is_device_specific else None)

        # Clear saved test results for this detector
        if det_name in self.test_results:
            del self.test_results[det_name]
            save_detector_results(self.test_results)

        self._lbl_manage_status.config(text=f"'{det_name}' image deleted.")
        self._refresh_manage_table()
        self._populate_detector_list()


# ---------------------------------------------------------------------------
# Helper dialog: shared vs device-specific
# ---------------------------------------------------------------------------

class _AskSaveScope:
    def __init__(self, parent, detector_name: str):
        self.result: Optional[str] = None
        self.top = tk.Toplevel(parent)
        self.top.title("Save Scope")
        self.top.grab_set()
        self.top.resizable(False, False)

        ttk.Label(
            self.top,
            text=f"Save '{detector_name}' as:",
            font=("TkDefaultFont", 10, "bold"),
            padding=(16, 12, 16, 4),
        ).pack()

        ttk.Label(
            self.top,
            text=(
                "Shared — same image works across all devices\n"
                "Device-specific — only for this device (different resolution or UI)"
            ),
            justify="left",
            padding=(16, 0, 16, 8),
            foreground="#555555",
        ).pack()

        btn_row = ttk.Frame(self.top, padding=(16, 4, 16, 16))
        btn_row.pack()
        ttk.Button(btn_row, text="Shared",
                   command=lambda: self._pick("shared")).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Device-Specific",
                   command=lambda: self._pick("device")).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Cancel",
                   command=self.top.destroy).pack(side="left")

        self.top.wait_window()

    def _pick(self, choice: str) -> None:
        self.result = choice
        self.top.destroy()
