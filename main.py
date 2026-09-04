"""
main.py

Fish Farm Manager — entry point.

Starts the core (DeviceManager) and the Tkinter UI.
The core runs regardless of UI visibility.
The UI reads from the core via polling — it never writes to worker state directly.

Usage:
    python main.py
"""

import sys
import tkinter as tk
from pathlib import Path

from bot import app_logger
from config.settings import load_settings, validate_settings
from config.devices import load_devices, validate_devices
from bot.device_manager import DeviceManager
from ui.app import App

PROJECT_ROOT = Path(__file__).resolve().parent


def main():
    # ---- Load configuration ----
    try:
        settings = load_settings()
        devices = load_devices()
    except Exception as e:
        # app_logger isn't configured yet at this point (that needs
        # settings.logging, which is what just failed to load) — its own
        # log() falls back to a console print in that case, so this still
        # goes through the one call site rather than a bespoke print.
        app_logger.log(f"[FATAL] Failed to load configuration: {e}", "CRITICAL")
        sys.exit(1)

    # ---- Start the persistent logger before anything else logs ----
    app_logger.configure(settings.logging, PROJECT_ROOT)

    # ---- Validate (warnings only — never fatal at startup) ----
    setting_warnings = validate_settings(settings)
    device_warnings = validate_devices(devices)
    all_warnings = setting_warnings + device_warnings

    for w in all_warnings:
        app_logger.log(w, level="WARNING")

    # ---- Start the device manager (core) ----
    # The log function is a placeholder here — replaced with the UI queue
    # once the App is constructed. Every call already reaches app_logger
    # (so it's on disk immediately); only the UI display is deferred.
    log_buffer = []

    def early_log(msg: str, level: str = "INFO"):
        log_buffer.append(msg)
        app_logger.log(msg, level)

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
    # Replay early log messages into the UI display only — they were
    # already written to app_logger above, so app.log() here would
    # double-write them to the file/console.
    for msg in log_buffer:
        app.display(msg)

    # Start all enabled device workers
    # manager.start_all()

    root.mainloop()

    # ---- Cleanup on window close ----
    manager.stop_all()


if __name__ == "__main__":
    main()
