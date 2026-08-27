"""
main.py

Be Fish Farm Manager — entry point.

Starts the core (DeviceManager) and the Tkinter UI.
The core runs regardless of UI visibility.
The UI reads from the core via polling — it never writes to worker state directly.

Usage:
    python main.py
"""

import sys
import tkinter as tk

from bot.config_manager import load_settings, load_devices, validate_settings, validate_devices
from bot.device_manager import DeviceManager
from ui.app import App


def main():
    # ---- Load configuration ----
    try:
        settings = load_settings()
        devices = load_devices()
    except Exception as e:
        print(f"[FATAL] Failed to load configuration: {e}")
        sys.exit(1)

    # ---- Validate (warnings only — never fatal at startup) ----
    setting_warnings = validate_settings(settings)
    device_warnings = validate_devices(devices)
    all_warnings = setting_warnings + device_warnings

    for w in all_warnings:
        print(f"[WARNING] {w}")

    # ---- Start the device manager (core) ----
    # The log function is a placeholder here — replaced with the UI queue
    # once the App is constructed. We pass a lambda that updates in place.
    log_buffer = []

    def early_log(msg: str):
        log_buffer.append(msg)
        print(msg)

    manager = DeviceManager(
        settings=settings,
        device_cfgs=devices,
        log_fn=early_log,
    )

    # ---- Start the Tkinter UI ----
    root = tk.Tk()
    app = App(root, manager=manager, startup_warnings=all_warnings)

    # Wire the manager's log function to the UI queue
    manager._log_fn = app.log
    # Replay any early log messages into the UI
    for msg in log_buffer:
        app.log(msg)

    # Start all enabled device workers
    # manager.start_all()

    root.mainloop()

    # ---- Cleanup on window close ----
    manager.stop_all()


if __name__ == "__main__":
    main()
