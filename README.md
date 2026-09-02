# Be Fish Farm Manager

A background device-farm manager for the Roblox game **Be Fish**. Runs on a Windows PC with a bank of Android phones/tablets connected over USB via an ADB hub. Each device gets its own worker thread that captures its screen, detects what's on it via image template matching (no OCR), and drives it through ADB taps — auto-farming, resetting timers, recovering from crashes, and keeping the device out of trouble (battery, heat, dropped ADB) — indefinitely and unattended.

One device is the **lead** (owns the tank, detects who ate it, signals the others); the rest are **support** (follow the lead, react to its signals). Devices can run in **private** server mode (one shared private tank) or **public** (public server, currently stubbed).

See [`BeFish_FarmManager_Plan.md`](BeFish_FarmManager_Plan.md) for the original architecture/design writeup, and [`AUDIT.md`](AUDIT.md) / [`ROADMAP.md`](ROADMAP.md) for where this codebase currently stands against the personal dev-standards checklist and what's being worked on next.

## Running it

```
pip install -r requirements.txt
python main.py
```

Requires `adb` (Android Platform Tools) and, for the primary capture backend, `scrcpy` — paths to both are set in `config/settings.json` (`adb_path`, `scrcpy_path`). First run: use **+ Add Devices** in the UI to scan connected ADB devices and configure them (role, profile, detector images, timers).

## What each folder does

| Folder | Responsibility |
|---|---|
| [`main.py`](main.py) | Entry point. Loads config, starts the core (`DeviceManager`), starts the Tkinter UI. The core runs independently of the UI. |
| [`bot/`](bot/) | The core: device lifecycle (`device_manager.py`), the per-device scan/detect/act loop (`device_worker.py`), state resolution (`state_machine.py`, `state_rules.py`, `states.py`), ADB input actions (`actions.py`), inter-device signaling (`farm_event_bus.py`), battery/temp/ADB health checks (`health_monitor.py`), and the persistent logging layer (`app_logger.py` — rotating `logs/app.log`, always-on `logs/errors.log`). |
| [`capture/`](capture/) | Screen capture backends. `base.py` defines the interface; `scrcpy_socket.py` is the primary backend (low-latency, no visible window); `adb_screencap.py` is the ADB-screencap fallback. |
| [`detection/`](detection/) | Template-matching engine. `detector.py` runs OpenCV `TM_CCOEFF_NORMED` matching; `template_bank.py` loads/caches detector images (shared vs. per-device overrides); `result.py` defines the `DetectResult` shape every detector returns. |
| [`config/`](config/) | All configuration, data and code. `settings.json` (global settings, not committed — see `.gitignore`), `devices.json` (per-device config, not committed), `profiles/*.yaml` (per-role state-detection rule sets and behaviors — `lead_private`, `support_private`, `lead_public`, `support_public`). Loaded/saved/validated by `settings.py`, `devices.py`, and `profiles.py` respectively (`profiles.py` is load-only — profiles are edited by hand, not through the UI), sharing path resolution from `paths.py`. |
| [`ui/`](ui/) | Tkinter UI. `app.py` is the main window (device list + log panel, polls the core, never touches worker internals directly); `device_panel.py`, `settings_dialog.py`, `device_settings_dialog.py`, `add_device_dialog.py` are the panel and dialogs. |
| [`tools/`](tools/) | Standalone utilities, launchable independently or from the UI: `image_capture_tool.py` (capture/crop/manage detector template images), `coordinate_finder.py` (click a live frame to read back screen coordinates for `click_offset`). |
| [`assets/`](assets/) | `shared/` — detector template images used by all devices unless overridden. `devices/{serial}/` — per-device image overrides. `scrcpy-server.jar` — pushed to devices by the scrcpy capture backend. |

## Key rules the code follows

- Workers never touch Tkinter. The UI only reads status (via polling) and writes to the config store — it never calls worker methods or reaches into worker internals directly.
- Every feature checks its own enabled flag on every loop iteration, not once at startup — config changes made in the UI take effect on the device's next scan, no restart required.
- All device state comes from image template matching against the live screen; there's no OCR and no reliance on a visible scrcpy window.
