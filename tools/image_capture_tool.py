"""
tools/image_capture_tool.py

Guided Image Capture & Crop Tool.

Walks through every detector required by a device's profile, one at a time:
  1. Shows which image is needed with instructions
  2. User manipulates the device to that state
  3. User clicks Ready -> app captures a live frame via ADB
  4. User drags to crop the region of interest
  5. User chooses shared or device-specific save
  6. Saved image resets click_offset to [0, 0] in devices.json
  7. Test button: captures live frame, runs match, shows result + confidence

Also handles the special case of eaten_by_name_image capture.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
import threading
from pathlib import Path
from typing import Optional, List
import subprocess

import cv2
import numpy as np
from PIL import Image, ImageTk

from bot.config_manager import (
    DeviceConfig, DetectorConfig,
    load_devices, save_devices,
)
from bot.config_manager import load_profile
from detection.template_bank import TemplateBank
from detection.detector import find_by_path


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
}

DEFAULT_INSTRUCTION = "Get the device to show this state, then press Ready."


class ImageCaptureTool:
    """
    Guided image capture wizard for one device.
    Launched from the device settings dialog.
    """

    def __init__(self, parent, device_cfg: DeviceConfig):
        self.parent = parent
        self.device_cfg = device_cfg
        self.bank = TemplateBank()

        # Load profile to get required detectors
        try:
            profile = load_profile(device_cfg.profile)
            self.required_detectors = profile.detectors_required
        except Exception:
            self.required_detectors = []

        # Add eaten_by_name as a special entry for all devices
        if "eaten_by_name" not in self.required_detectors:
            self.required_detectors = list(self.required_detectors) + ["eaten_by_name"]

        # State
        self._current_frame: Optional[np.ndarray] = None
        self._crop_start: Optional[tuple] = None
        self._crop_rect: Optional[tuple] = None   # (x1, y1, x2, y2) in image coords
        self._canvas_scale = 1.0
        self._canvas_offset = (0, 0)
        self._photo: Optional[ImageTk.PhotoImage] = None
        self._rect_id = None
        self._selected_detector: Optional[str] = None

        self._build()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build(self) -> None:
        self.top = tk.Toplevel(self.parent)
        self.top.title(f"Image Capture Tool — {self.device_cfg.nickname or self.device_cfg.serial}")
        self.top.geometry("1100x720")
        self.top.resizable(True, True)

        # Main paned layout: left = detector list, right = capture/crop area
        paned = ttk.PanedWindow(self.top, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=8)

        # ---- Left panel: detector list ----
        left = ttk.Frame(paned, width=260)
        paned.add(left, weight=0)

        ttk.Label(left, text="Required Detectors",
                  font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(0, 6))

        list_frame = ttk.Frame(left)
        list_frame.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")

        self._detector_list = tk.Listbox(
            list_frame, yscrollcommand=scrollbar.set,
            selectmode="single", width=30, activestyle="none"
        )
        self._detector_list.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self._detector_list.yview)
        self._detector_list.bind("<<ListboxSelect>>", self._on_detector_select)

        # ---- Right panel: capture and crop area ----
        right = ttk.Frame(paned)
        paned.add(right, weight=1)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        # Instruction label
        self._lbl_instruction = ttk.Label(
            right, text="Select a detector from the list to begin.",
            wraplength=700, justify="left",
            font=("TkDefaultFont", 10),
        )
        self._lbl_instruction.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        # Action buttons row
        btn_row = ttk.Frame(right)
        btn_row.grid(row=1, column=0, sticky="w", pady=(0, 6))

        self._btn_ready = ttk.Button(
            btn_row, text="Ready — Capture Frame",
            command=self._capture_frame, state="disabled"
        )
        self._btn_ready.pack(side="left", padx=(0, 8))

        self._btn_save = ttk.Button(
            btn_row, text="Save Crop",
            command=self._save_crop, state="disabled"
        )
        self._btn_save.pack(side="left", padx=(0, 8))

        self._btn_test = ttk.Button(
            btn_row, text="Test Detection",
            command=self._test_detection, state="disabled"
        )
        self._btn_test.pack(side="left", padx=(0, 8))

        self._lbl_result = ttk.Label(btn_row, text="")
        self._lbl_result.pack(side="left", padx=(12, 0))

        # Canvas for displaying captured frame and drawing crop
        canvas_frame = ttk.Frame(right, relief="sunken", borderwidth=1)
        canvas_frame.grid(row=2, column=0, sticky="nsew")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        self._canvas = tk.Canvas(canvas_frame, bg="#1a1a1a", cursor="crosshair")
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._canvas.bind("<ButtonPress-1>", self._on_mouse_down)
        self._canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_mouse_up)

        # Status bar
        self._lbl_status = ttk.Label(
            right, text="No frame captured.", foreground="#888888"
        )
        self._lbl_status.grid(row=3, column=0, sticky="w", pady=(4, 0))

        # Populate detector list
        self._populate_list()

    # ------------------------------------------------------------------
    # Detector list
    # ------------------------------------------------------------------

    def _populate_list(self) -> None:
        """Fill the listbox with detector names and status icons."""
        self._detector_list.delete(0, "end")
        for name in self.required_detectors:
            status = self._detector_status(name)
            icon = {"ok": "✓", "missing": "✗", "untested": "?"}.get(status, "?")
            self._detector_list.insert("end", f"  {icon}  {name}")
            color = {"ok": "#00aa44", "missing": "#cc2222", "untested": "#aa8800"}.get(status, "#888888")
            self._detector_list.itemconfig("end", foreground=color)

    def _detector_status(self, name: str) -> str:
        """Return 'ok', 'missing', or 'untested' for a detector."""
        if name == "eaten_by_name":
            path = self.device_cfg.eaten_by_name_image
            return "ok" if path and Path(path).exists() else "missing"

        exists = self.bank.exists(name, self.device_cfg.serial, self.device_cfg.device_image_overrides)
        # We mark existing images as 'untested' until a test is run this session
        return "untested" if exists else "missing"

    def _on_detector_select(self, event) -> None:
        """User clicked a detector in the list."""
        sel = self._detector_list.curselection()
        if not sel:
            return
        idx = sel[0]
        name = self.required_detectors[idx]
        self._selected_detector = name

        instruction = DETECTOR_INSTRUCTIONS.get(name, DEFAULT_INSTRUCTION)
        self._lbl_instruction.config(text=f"Detector: {name}\n\n{instruction}")
        self._btn_ready.config(state="normal")
        self._btn_save.config(state="disabled")
        self._lbl_result.config(text="")

        # Enable test button only if image already exists
        if self._detector_status(name) != "missing":
            self._btn_test.config(state="normal")
        else:
            self._btn_test.config(state="disabled")

        self._clear_canvas()

    # ------------------------------------------------------------------
    # Frame capture
    # ------------------------------------------------------------------

    def _capture_frame(self) -> None:
        """Capture a live frame from the device via ADB screencap."""
        self._btn_ready.config(state="disabled")
        self._lbl_status.config(text="Capturing frame...")
        self.top.update_idletasks()

        def do_capture():
            try:
                result = subprocess.run(
                    ["adb", "-s", self.device_cfg.serial,
                     "exec-out", "screencap", "-p"],
                    capture_output=True, timeout=10,
                )
                if result.returncode != 0 or not result.stdout:
                    self.top.after(0, lambda: self._capture_failed("ADB screencap returned no data"))
                    return

                img_array = np.frombuffer(result.stdout, dtype=np.uint8)
                frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
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
        self._lbl_result.config(text="")
        h, w = frame.shape[:2]
        self._lbl_status.config(text=f"Frame captured: {w}x{h}. Drag to crop the target region.")
        self._display_frame(frame)

    def _capture_failed(self, reason: str) -> None:
        self._btn_ready.config(state="normal")
        self._lbl_status.config(text=f"Capture failed: {reason}", foreground="red")

    # ------------------------------------------------------------------
    # Canvas display and crop drawing
    # ------------------------------------------------------------------

    def _display_frame(self, frame: np.ndarray) -> None:
        """Scale the frame to fit the canvas and display it."""
        canvas_w = self._canvas.winfo_width() or 800
        canvas_h = self._canvas.winfo_height() or 500

        fh, fw = frame.shape[:2]
        scale = min(canvas_w / fw, canvas_h / fh, 1.0)
        new_w = int(fw * scale)
        new_h = int(fh * scale)

        self._canvas_scale = scale
        self._canvas_offset = (
            (canvas_w - new_w) // 2,
            (canvas_h - new_h) // 2,
        )

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb).resize((new_w, new_h), Image.LANCZOS)
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

    # ---- Mouse events for crop rectangle ----

    def _canvas_to_image(self, cx: int, cy: int) -> tuple:
        """Convert canvas pixel coords to image pixel coords."""
        ox, oy = self._canvas_offset
        scale = self._canvas_scale
        ix = int((cx - ox) / scale)
        iy = int((cy - oy) / scale)
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
            outline="#00ff88", width=2, dash=(4, 2)
        )

    def _on_mouse_up(self, event) -> None:
        if not self._crop_start or self._current_frame is None:
            return
        x0, y0 = self._crop_start
        x1, y1 = event.x, event.y

        # Convert both corners to image coords
        ix0, iy0 = self._canvas_to_image(min(x0, x1), min(y0, y1))
        ix1, iy1 = self._canvas_to_image(max(x0, x1), max(y0, y1))

        if ix1 - ix0 < 5 or iy1 - iy0 < 5:
            self._lbl_status.config(text="Crop too small. Drag a larger region.")
            return

        self._crop_rect = (ix0, iy0, ix1, iy1)
        w = ix1 - ix0
        h = iy1 - iy0
        self._lbl_status.config(text=f"Crop selected: {w}x{h} at ({ix0}, {iy0}). Click Save Crop to save.")
        self._btn_save.config(state="normal")

    # ------------------------------------------------------------------
    # Save crop
    # ------------------------------------------------------------------

    def _save_crop(self) -> None:
        if self._current_frame is None or self._crop_rect is None:
            return
        if not self._selected_detector:
            return

        name = self._selected_detector
        ix0, iy0, ix1, iy1 = self._crop_rect
        crop = self._current_frame[iy0:iy1, ix0:ix1]

        if crop.size == 0:
            messagebox.showerror("Error", "Crop region is empty.", parent=self.top)
            return

        # eaten_by_name is always device-specific
        if name == "eaten_by_name":
            self._save_eaten_by_name(crop)
            return

        # Ask: shared or device-specific?
        choice = _AskSaveScope(self.top, name).result
        if choice is None:
            return  # cancelled

        save_as_device = (choice == "device")
        self._do_save(crop, name, save_as_device)

    def _do_save(self, crop: np.ndarray, name: str, device_specific: bool) -> None:
        """Save the cropped image and update devices.json."""
        project_root = Path(__file__).resolve().parent.parent

        if device_specific:
            out_dir = project_root / "assets" / "devices" / self.device_cfg.serial
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{name}.png"
        else:
            out_dir = project_root / "assets" / "shared"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{name}.png"

        cv2.imwrite(str(out_path), crop)

        # Update devices.json
        devices = load_devices()
        for dev in devices:
            if dev.serial == self.device_cfg.serial:
                # Update device_image_overrides
                overrides = list(dev.device_image_overrides)
                if device_specific and name not in overrides:
                    overrides.append(name)
                elif not device_specific and name in overrides:
                    overrides.remove(name)
                dev.device_image_overrides = overrides

                # Reset click_offset for this detector
                if name not in dev.detectors:
                    dev.detectors[name] = DetectorConfig(
                        image=str(out_path.relative_to(project_root)),
                        click_offset=[0, 0],
                    )
                else:
                    dev.detectors[name].image = str(out_path.relative_to(project_root))
                    dev.detectors[name].click_offset = [0, 0]

                # Update our local copy
                self.device_cfg = dev
                break

        save_devices(devices)

        # Invalidate template bank cache so the new image loads on next detection
        if device_specific:
            self.bank.invalidate(name, self.device_cfg.serial)
        else:
            self.bank.invalidate(name, None)

        self._btn_test.config(state="normal")
        self._lbl_status.config(
            text=f"Saved: {out_path.name} ({'device-specific' if device_specific else 'shared'}). "
                 f"Click_offset reset to [0,0]. Run Test Detection to verify."
        )
        self._populate_list()

    def _save_eaten_by_name(self, crop: np.ndarray) -> None:
        """Save the eaten-by name image for this device."""
        project_root = Path(__file__).resolve().parent.parent
        out_dir = project_root / "assets" / "devices" / self.device_cfg.serial
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "eaten_by_name.png"

        cv2.imwrite(str(out_path), crop)

        # Update devices.json
        devices = load_devices()
        for dev in devices:
            if dev.serial == self.device_cfg.serial:
                dev.eaten_by_name_image = str(out_path.relative_to(project_root))
                self.device_cfg = dev
                break

        save_devices(devices)
        self.bank.invalidate_by_path(str(out_path))

        self._lbl_status.config(
            text=f"Saved eaten_by_name image for {self.device_cfg.nickname or self.device_cfg.serial}. "
                 f"Run Test Detection to verify."
        )
        self._btn_test.config(state="normal")
        self._populate_list()

    # ------------------------------------------------------------------
    # Test detection
    # ------------------------------------------------------------------

    def _test_detection(self) -> None:
        """Capture a live frame and run template match against the saved image."""
        if not self._selected_detector:
            return

        self._lbl_result.config(text="Testing...", foreground="#888888")
        self._btn_test.config(state="disabled")
        self.top.update_idletasks()

        def do_test():
            # Capture live frame
            try:
                result = subprocess.run(
                    ["adb", "-s", self.device_cfg.serial,
                     "exec-out", "screencap", "-p"],
                    capture_output=True, timeout=10,
                )
                if result.returncode != 0 or not result.stdout:
                    self.top.after(0, lambda: self._test_done(None, "Capture failed"))
                    return

                img_array = np.frombuffer(result.stdout, dtype=np.uint8)
                frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                if frame is None:
                    self.top.after(0, lambda: self._test_done(None, "Decode failed"))
                    return

            except Exception as e:
                self.top.after(0, lambda: self._test_done(None, str(e)))
                return

            # Run match
            name = self._selected_detector
            try:
                if name == "eaten_by_name":
                    path = self.device_cfg.eaten_by_name_image
                    if not path:
                        self.top.after(0, lambda: self._test_done(None, "No eaten_by_name image saved"))
                        return
                    detect_result = find_by_path(
                        frame_bgr=frame,
                        image_path=path,
                        bank=self.bank,
                        detector_name="eaten_by_name",
                    )
                else:
                    from detection.detector import run_detector_by_name
                    detect_result = run_detector_by_name(
                        detector_name=name,
                        frame_bgr=frame,
                        device_serial=self.device_cfg.serial,
                        device_overrides=self.device_cfg.device_image_overrides,
                        bank=self.bank,
                    )

                self.top.after(0, lambda r=detect_result, f=frame: self._test_done(r, None, f))

            except Exception as e:
                self.top.after(0, lambda: self._test_done(None, str(e)))

        threading.Thread(target=do_test, daemon=True).start()

    def _test_done(self, result, error: Optional[str], frame=None) -> None:
        self._btn_test.config(state="normal")

        if error:
            self._lbl_result.config(text=f"Error: {error}", foreground="#cc2222")
            return

        if result.found:
            score_pct = int((result.score or 0) * 100)
            self._lbl_result.config(
                text=f"✓ FOUND  confidence={score_pct}%  center={result.center}",
                foreground="#00cc55"
            )
            # Show the test frame with match highlighted
            if frame is not None:
                annotated = frame.copy()
                if result.bbox:
                    x, y, w, h = result.bbox
                    cv2.rectangle(annotated, (x, y), (x+w, y+h), (0, 255, 128), 2)
                    cx, cy = result.center
                    cv2.circle(annotated, (cx, cy), 6, (0, 255, 128), -1)
                self._display_frame(annotated)

            # Update status indicator in list to 'ok'
            idx = self.required_detectors.index(self._selected_detector)
            self._detector_list.itemconfig(idx, foreground="#00aa44")
            text = self._detector_list.get(idx)
            self._detector_list.delete(idx)
            self._detector_list.insert(idx, text.replace("  ?  ", "  ✓  ").replace("  ✗  ", "  ✓  "))
            self._detector_list.itemconfig(idx, foreground="#00aa44")
            self._detector_list.selection_set(idx)
        else:
            score_pct = int((result.score or 0) * 100)
            self._lbl_result.config(
                text=f"✗ NOT FOUND  best score={score_pct}%  (threshold ~82%)",
                foreground="#cc2222"
            )
            if frame is not None:
                self._display_frame(frame)


# ---------------------------------------------------------------------------
# Helper dialog: ask shared vs device-specific
# ---------------------------------------------------------------------------

class _AskSaveScope:
    """Small modal dialog to ask whether to save shared or device-specific."""

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
            text="Shared — works across all devices (same screen resolution)\n"
                 "Device-specific — only for this device (different resolution/screen)",
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
