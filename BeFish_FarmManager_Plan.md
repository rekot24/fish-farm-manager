# Be Fish — Phone Farm Manager
## Architecture & Build Plan

**Last Updated:** 2026-08-25  
**Status:** Final — Ready to Build  
**Scope:** Android device farm manager (phones/tablets only)

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [What This Is Not](#2-what-this-is-not)
3. [Project Structure](#3-project-structure)
4. [Configuration Schema](#4-configuration-schema)
5. [The 4 Profiles](#5-the-4-profiles)
6. [Device Worker Architecture](#6-device-worker-architecture)
7. [Screen Capture Backend](#7-screen-capture-backend)
8. [State Machine & Detection System](#8-state-machine--detection-system)
9. [Image Capture & Crop Tool](#9-image-capture--crop-tool)
10. [Input System](#10-input-system)
11. [Device Health Monitoring](#11-device-health-monitoring)
12. [Crash Detection & Recovery](#12-crash-detection--recovery)
13. [Auto-Farm Reset Logic](#13-auto-farm-reset-logic)
14. [End-Run Reset Logic](#14-end-run-reset-logic)
15. [Lead-Eaten Detection](#15-lead-eaten-detection)
16. [UI Structure](#16-ui-structure)
17. [Phase Plan](#17-phase-plan)
18. [Key Principles](#18-key-principles)

---

## 1. Project Overview

A background Android device farm manager for Be Fish. Manages up to 10+ phones/tablets
connected via USB to an ADB hub. Runs headlessly (minimized window) by default. Each device
gets its own worker thread running an independent loop. The UI connects to the already-running
core and is used for monitoring, configuration, and on-demand control.

**Core goals:**
- All devices stay in the private tank (server), indefinitely, automatically
- Lead device owns the tank; support devices follow
- Automatic crash recovery and server rejoin
- Device health monitoring (battery, heat, ADB connection)
- Image-based state detection only (no OCR)
- Built to scale, built to extend

---

## 2. What This Is Not

- Not a PC Roblox automator (that is a separate existing tool)
- Not dependent on scrcpy windows (added in a future phase)
- Not using OCR (all detection is template matching via saved image crops)
- Not managing public server logic in Phase 1 (public profiles are stubbed but not implemented)

---

## 3. Project Structure

```
BE_FISH_FARM/
│
├── main.py                         # Entry point, starts core + UI
│
├── bot/
│   ├── __init__.py
│   ├── device_manager.py           # Discovers ADB devices, spawns/manages workers
│   ├── device_worker.py            # Per-device thread: capture → detect → act loop
│   ├── state_machine.py            # Priority-rule state resolver
│   ├── state_rules.py              # Rule definitions per profile
│   ├── states.py                   # State name constants
│   ├── profiles.py                 # Profile loader and behavior dispatcher
│   ├── actions.py                  # ADB action helpers (tap, swipe, key events)
│   ├── farm_event_bus.py           # Inter-device signaling (cascade reset, eaten-by)
│   ├── health_monitor.py           # Battery, temperature, ADB connection watchdog
│   └── crash_detector.py          # Roblox process and game state crash detection
│
├── capture/
│   ├── __init__.py
│   ├── base.py                     # CaptureBackend abstract base class
│   ├── scrcpy_socket.py            # Scrcpy socket backend (primary)
│   └── adb_screencap.py            # ADB screencap backend (fallback)
│
├── detection/
│   ├── __init__.py
│   ├── detector.py                 # Template matching engine (OpenCV TM_CCOEFF_NORMED)
│   ├── template_bank.py            # Loads and caches template images in memory
│   └── result.py                   # DetectResult dataclass
│
├── config/
│   ├── settings.json               # Global app settings
│   ├── devices.json                # Per-device configuration list
│   └── profiles/
│       ├── lead_private.yaml       # Lead Private profile behavior
│       ├── support_private.yaml    # Support Private profile behavior
│       ├── lead_public.yaml        # Lead Public profile (stubbed Phase 1)
│       └── support_public.yaml     # Support Public profile (stubbed Phase 1)
│
├── assets/
│   ├── shared/                     # Detection images that work across all devices
│   │   ├── auto_button_on.png
│   │   ├── auto_button_off.png
│   │   ├── end_run_button.png
│   │   ├── death_screen.png
│   │   └── ...
│   └── devices/
│       └── {device_serial}/        # Per-device detection images (resolution overrides)
│           ├── eaten_by_name.png   # This device's in-game name as seen on death screen
│           └── ...                 # Any shared image that needed a device-specific override
│
├── tools/
│   ├── image_capture_tool.py       # Guided image capture, crop, and test tool
│   └── coordinate_finder.py        # ADB-based coordinate helper
│
└── ui/
    ├── __init__.py
    ├── app.py                      # Main Tkinter window
    ├── device_panel.py             # Per-device status row in device list
    ├── device_settings_dialog.py   # Per-device settings popup
    └── settings_dialog.py          # Global settings popup
```

---

## 4. Configuration Schema

### 4.1 `settings.json` — Global Settings

```json
{
  "adb_path": "adb",
  "scan_interval_ms": 800,
  "template_confidence_default": 0.82,
  "private_server_link": "https://www.roblox.com/games/...",
  "health": {
    "battery_min_percent": 20,
    "battery_resume_percent": 80,
    "temp_throttle_celsius": 45,
    "temp_pause_celsius": 52,
    "temp_resume_celsius": 40,
    "adb_reconnect_interval_s": 10
  },
  "debug": {
    "save_failed_captures": true,
    "log_state_changes": true,
    "screenshot_dir": "debug_shots"
  }
}
```

### 4.2 `devices.json` — Per-Device Configuration

Array of device objects. One entry per physical device.

```json
[
  {
    "serial": "XXXXXXXXXXXXXXXX",
    "nickname": "Pixel 7 - Alpha",
    "model": "Pixel 7",
    "enabled": true,
    "is_lead": true,
    "profile": "lead_private",
    "scan_interval_ms": 800,
    "detectors": {
      "auto_button_on": {
        "image": "assets/shared/auto_button_on.png",
        "click_offset": [0, 0]
      },
      "end_run_button": {
        "image": "assets/shared/end_run_button.png",
        "click_offset": [0, 0]
      },
      "death_to_lobby": {
        "image": "assets/devices/XXXXXXXXXXXXXXXX/death_to_lobby.png",
        "click_offset": [0, 0]
      }
    },
    "timers": {
      "auto_farm_reset_interval_min": 15,
      "end_run_reset_interval_min": 10
    },
    "eaten_by_name_image": "assets/devices/XXXXXXXXXXXXXXXX/eaten_by_name.png",
    "device_image_overrides": ["death_to_lobby"],
    "notes": ""
  }
]
```

**Rules:**
- Only one device may have `"is_lead": true` — enforced by the app
- `profile` must match a filename in `config/profiles/`
- `detectors` — each entry holds the image path and an optional `click_offset`
  relative to the detected image center. `[0, 0]` means click dead center.
  Most actions click center of the detected image; offset allows fine-tuning
  without a separate coord system.
- `device_image_overrides` — list of detector names using device-specific images
  instead of shared. Maintained automatically by the Image Capture Tool.
- `timers` are per-device and GUI-adjustable at runtime

### 4.3 Profile YAML Schema

```yaml
# Example: support_private.yaml
profile_name: support_private
role: support
server_type: private

behaviors:
  auto_farm_reset:
    enabled: true
    interval_min: 15         # Default; overridden by per-device timer setting

  end_run_reset:
    enabled: true
    interval_min: 10         # Default; overridden by per-device timer setting

  rejoin_on_kick: true
  rejoin_target: lead        # Join wherever the lead device is

  cascade_reset_on_lead_reset:
    enabled: true
    delay_after_lead_s: 30   # Reset this many seconds after lead resets

detectors_required:
  - auto_button_on
  - auto_button_off
  - end_run_button
  - death_screen
  - in_run_indicator
  - lobby_screen
```

---

## 5. The 4 Profiles

### 5.1 Lead Private

- Owns the private tank; `private_server_link` stored in its device config
- Runs auto-farm
- Resets auto-farm every X minutes (double-click auto button)
- Resets end-run on its own interval
- On death: checks eaten-by name, identifies which support device ate it,
  triggers end-run on that device via FarmEventBus
- On crash: relaunch Roblox, rejoin own private tank using stored server link

### 5.2 Support Private

- Stays in lead's private tank
- Runs auto-farm
- Resets auto-farm every X minutes (double-click auto button)
- Resets end-run on its own interval (per-device, GUI-adjustable)
- Listens for cascade-reset signal from lead via FarmEventBus
- On kick/crash: auto-rejoin lead's tank silently using lead's `private_server_link`
- No screenshot saving on death

### 5.3 Lead Public *(Phase 1 stub only)*

- Different routine for public servers
- On death: save eaten-by screen capture for reference (no logic action)
- Full implementation deferred to Phase 2

### 5.4 Support Public *(Phase 1 stub only)*

- Follows lead on public servers
- Full implementation deferred to Phase 2

---

## 6. Device Worker Architecture

Each connected device runs one independent worker thread. Threads do not share state
except through thread-safe signals (Python `threading.Event` and `queue.Queue`).

### 6.1 Worker Loop

```
DeviceWorker.run():
  while not stop_event:
    1. Health check (battery, temp, ADB connection)
       → if battery critical: enter battery_sleep_mode()
       → if temp critical: enter temp_pause_mode()
       → if ADB dropped: attempt reconnect, skip scan

    2. Poll FarmEventBus for incoming events (cascade_reset, force_end_run)

    3. Capture frame (CaptureBackend.get_frame())

    4. Run detectors → results dict

    5. Resolve state (state_machine.resolve_state(results))

    6. Dispatch action (profile_behavior.act(state, device_context))
       → auto-farm reset timer check
       → end-run reset timer check
       → state-based click actions

    7. Sleep (scan_interval_ms - elapsed, minimum 50ms)
```

### 6.2 Inter-Device Signaling

The lead device signals support devices (cascade reset, eaten-by trigger) via
`FarmEventBus` — a simple dict of `queue.Queue` objects, one per device serial.
The lead posts an event; the target device's worker reads it at the top of its
next loop iteration.

```python
# Lead posts to a specific device:
event_bus.post(target_serial="XXXX", event={"type": "cascade_reset"})

# Lead posts to all support devices:
event_bus.broadcast(event={"type": "cascade_reset"}, exclude_serial=self.serial)

# Support reads at top of loop:
event = event_bus.poll(self.serial)
if event and event["type"] == "cascade_reset":
    self.schedule_end_run(delay_s=self.profile.cascade_delay_s)
```

### 6.3 DeviceManager

Runs on the main thread. Responsibilities:
- Poll `adb devices` on startup and periodically
- Spawn a `DeviceWorker` thread per connected and enabled device
- Hold references to all workers for UI status polling
- Handle device connect/disconnect events
- Own the single shared `FarmEventBus` instance passed to all workers

---

## 7. Screen Capture Backend

The `CaptureBackend` abstraction supports multiple implementations. Scrcpy socket
is the primary backend from day one — it delivers real-time frames without a visible
window, runs well under 100ms per frame, and handles 10+ devices cleanly.
ADB screencap is retained as a fallback for devices that have trouble with scrcpy.

### 7.1 Abstract Base

```python
# capture/base.py
class CaptureBackend(ABC):
    @abstractmethod
    def get_frame(self) -> np.ndarray:
        """Returns a BGR numpy array of the current device screen."""
        pass

    @abstractmethod
    def connect(self) -> bool:
        pass

    @abstractmethod
    def disconnect(self) -> None:
        pass
```

### 7.2 Scrcpy Socket Backend (Primary)

Scrcpy has a server mode that streams H.264 frames over a local socket with no
visible window. The implementation has three stages:

**Stage 1 — Push and start the scrcpy server on the device:**
```python
# Push the scrcpy-server.jar to the device
subprocess.run(["adb", "-s", serial, "push", "scrcpy-server.jar", "/data/local/tmp/"])

# Forward a local TCP port to the device
subprocess.run(["adb", "-s", serial, "forward", "tcp:27183", "localabstract:scrcpy"])

# Start the scrcpy server on the device
subprocess.run(["adb", "-s", serial, "shell",
    "CLASSPATH=/data/local/tmp/scrcpy-server.jar",
    "app_process", "/", "com.genymobile.scrcpy.Server",
    "2.x", "tunnel_forward=true", "video_bit_rate=2000000",
    "max_size=0", "control=false"
])
```

**Stage 2 — Connect the socket and read the stream header:**
```python
sock = socket.create_connection(("127.0.0.1", 27183), timeout=5)
# Read and discard the 64-byte device metadata header
header = sock.recv(64)
# Read the video stream header (codec, width, height)
video_header = sock.recv(12)
```

**Stage 3 — Decode H.264 frames continuously:**
```python
# Use PyAV (ffmpeg bindings) to decode the H.264 bytestream
# Each decoded frame is converted to a BGR numpy array
import av
codec = av.CodecContext.create("h264", "r")
# Feed chunks from socket → decode → yield np.ndarray frames
```

**Expected performance:** Sub-100ms per frame. Suitable for 10+ simultaneous devices.

```python
# capture/scrcpy_socket.py
class ScrcpySocketBackend(CaptureBackend):
    def connect(self) -> bool:
        # Push server, forward port, start server process, open socket
        # Read and validate stream headers
        # Initialize PyAV decoder

    def get_frame(self) -> np.ndarray:
        # Read next H.264 packet from socket
        # Decode via PyAV
        # Return BGR numpy array

    def disconnect(self) -> None:
        # Close socket, kill server process, remove adb forward
```

### 7.3 ADB Screencap (Fallback)

Retained as a fallback for devices that have scrcpy compatibility issues.
Selectable per-device in the device settings dialog.

```python
# capture/adb_screencap.py
class ADBScreencapBackend(CaptureBackend):
    def get_frame(self) -> np.ndarray:
        result = subprocess.run(
            ["adb", "-s", self.serial, "exec-out", "screencap", "-p"],
            capture_output=True, timeout=5
        )
        img_array = np.frombuffer(result.stdout, dtype=np.uint8)
        frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        return frame
```

**Expected performance:** 300-500ms per capture. Use only if scrcpy socket fails.

### 7.4 Backend Selection

Each device can independently use either backend. Configured per-device in
the device settings dialog. Stored in `devices.json` as `"capture_backend": "scrcpy"`
or `"capture_backend": "adb"`. Default is `"scrcpy"`.

The `DeviceWorker` instantiates the correct backend at startup based on this setting.
Switching backends requires restarting that device's worker.

### 7.5 Scrcpy Viewer Windows (Future Phase)

On-demand per-device viewer panels using scrcpy's display mode (separate from
the socket capture). Launch/kill scrcpy process per device on toggle.
`DeviceWorker` holds a `viewer_pid` slot reserved for this. No other changes
needed to the worker loop when this is added.

---

## 8. State Machine & Detection System

### 8.1 Template Bank

Loads and caches all detection images at startup. Resolves which image to use
(shared vs device-specific override) based on `device_image_overrides` in device config.

```python
# detection/template_bank.py
class TemplateBank:
    def get(self, detector_name: str, device_serial: str) -> np.ndarray:
        # 1. Check device_image_overrides — load from assets/devices/{serial}/
        # 2. Fall back to assets/shared/
        # 3. Cache result in memory after first load
        # 4. Raise clear error if neither path exists
```

### 8.2 Detector Engine

Uses OpenCV `TM_CCOEFF_NORMED`. Returns the best match location and confidence score.
The `DetectResult` includes the bounding box center, which is used as the default
click target. A per-detector `click_offset` from `devices.json` shifts the click
relative to that center.

```python
# detection/detector.py
def find_in_frame(
    frame_bgr: np.ndarray,
    templates: list[np.ndarray],
    threshold: float = 0.82
) -> DetectResult:
    # Returns DetectResult with:
    #   found: bool
    #   bbox: (x, y, w, h)         — top-left + size in screen coords
    #   center: (cx, cy)            — center of matched region
    #   score: float                — match confidence
```

### 8.3 Click Target Resolution

When an action needs to click a detected element:

```python
def resolve_click_target(result: DetectResult, click_offset: tuple[int, int]) -> tuple[int, int]:
    cx, cy = result.center
    ox, oy = click_offset
    return (cx + ox, cy + oy)
```

This means coordinates do not need to be manually entered for most actions.
They are derived live from each detection. The stored `click_offset` in
`devices.json` is only needed when the tap target is not the image center
(e.g., a button where the active area is offset from the icon).

When a detection image is recaptured via the Image Capture Tool, its stored
`click_offset` resets to `[0, 0]` since the image geometry may have changed.

### 8.4 State Machine

Priority-ordered rule evaluation. Profile-specific rule sets.

```python
# bot/state_machine.py
def resolve_state(results: dict[str, DetectResult], profile: str) -> str:
    rules = STATE_RULES[profile]
    rules_sorted = sorted(rules, key=lambda r: r["priority"], reverse=True)
    for rule in rules_sorted:
        if all_required_found(rule, results) and none_excluded_found(rule, results):
            return rule["state"]
    return STATE_UNKNOWN
```

### 8.5 Core States (Private Mode)

| State | Description |
|---|---|
| `IN_RUN` | Auto-farming in progress |
| `DEAD` | Death screen visible |
| `LOBBY` | In game lobby, not in a tank |
| `LOADING` | Loading screen |
| `DISCONNECTED` | Lost from tank / kicked |
| `JOINING` | Currently joining a tank |
| `CRASHED` | Roblox not responding or not running |
| `UNKNOWN` | No rules matched |

---

## 9. Image Capture & Crop Tool

A guided wizard that walks through every required detection image for a given device.
Accessible from the device settings dialog via [Open Image Capture Tool].

### 9.1 Flow

1. **Device selector** — choose which device to set up images for
2. **Detector list** — shows all detectors the selected profile requires,
   with a status indicator:
   - 🟢 Green = image exists and last test passed
   - 🔴 Red = image missing
   - 🟡 Yellow = image exists but untested or test not yet run
3. **Guided capture per detector:**
   - Instruction text: *"Get the device to show: [detector description]. Press Ready when visible."*
   - **Ready** button → captures live frame via ADB screencap
   - Captured frame displayed in a canvas
   - User drags to draw a crop rectangle over the target element
   - **Save Crop** → prompts: *"Save as shared (all devices) or device-specific (this device only)?"*
   - Saves image to correct path; updates `devices.json` automatically
   - Resets `click_offset` to `[0, 0]` for this detector on save
4. **Test button (per detector):**
   - Captures a live frame from the device
   - Runs template match against the saved image
   - Shows: FOUND / NOT FOUND + confidence score + highlights match location on frame
   - Updates the status indicator accordingly

### 9.2 Shared vs Device-Specific

If saved as device-specific:
- Image saved to `assets/devices/{serial}/{detector_name}.png`
- Detector name added to `device_image_overrides` in `devices.json` automatically

If saved as shared:
- Image saved to `assets/shared/{detector_name}.png`
- Detector name removed from `device_image_overrides` if previously listed

### 9.3 Eaten-By Name Image

Always device-specific. The tool prompts:
*"Get any device to a death screen where this device's character name is visible. Press Ready."*
Guides the crop over the name text region. Saved to
`assets/devices/{serial}/eaten_by_name.png`.

### 9.4 Recapture Behavior

Recapturing an existing detector image:
- Overwrites the saved image file
- Resets `click_offset` to `[0, 0]` in `devices.json`
- Clears the test status back to 🟡 Yellow (untested)
- Does NOT change shared/device-specific designation unless the user explicitly changes it

---

## 10. Input System

All input sent via ADB. No Win32, no pyautogui, no scrcpy input (Phase 1).

```python
# bot/actions.py

def tap(serial: str, x: int, y: int) -> None:
    subprocess.run(["adb", "-s", serial, "shell", "input", "tap", str(x), str(y)])

def double_tap(serial: str, x: int, y: int, interval_ms: int = 100) -> None:
    tap(serial, x, y)
    time.sleep(interval_ms / 1000)
    tap(serial, x, y)

def swipe(serial: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 200) -> None:
    subprocess.run(["adb", "-s", serial, "shell", "input", "swipe",
                    str(x1), str(y1), str(x2), str(y2), str(duration_ms)])

def key_event(serial: str, keycode: int) -> None:
    subprocess.run(["adb", "-s", serial, "shell", "input", "keyevent", str(keycode)])

def wake_device(serial: str) -> None:
    key_event(serial, 224)  # KEYCODE_WAKEUP

def sleep_device(serial: str) -> None:
    key_event(serial, 223)  # KEYCODE_SLEEP

def launch_roblox(serial: str, package: str = "com.roblox.client") -> None:
    subprocess.run(["adb", "-s", serial, "shell", "monkey", "-p",
                    package, "-c", "android.intent.category.LAUNCHER", "1"])

def join_server_by_link(serial: str, link: str) -> None:
    """Launch Roblox directly into a private server via deep link intent."""
    subprocess.run([
        "adb", "-s", serial, "shell", "am", "start",
        "-a", "android.intent.action.VIEW",
        "-d", link,
        "com.roblox.client"
    ])
```

### 10.1 Click Target Resolution

Most actions click the center of a detected image. The full resolution chain:

```
1. Run detector → DetectResult (contains bbox and center in screen coords)
2. Read click_offset for this detector from devices.json
3. Final tap target = center + offset
4. Call tap(serial, x, y)
```

Click offsets are stored per-detector per-device in `devices.json` and are
editable via the device settings dialog. They reset to `[0, 0]` when the
detector image is recaptured.

Some actions (like rejoining a server) use a stored deep link rather than
a click coordinate — see `join_server_by_link()` above.

---

## 11. Device Health Monitoring

Runs as part of each device worker's loop, checked at the top of every iteration.

### 11.1 Battery Management

```
Poll: adb shell dumpsys battery | grep level

< battery_min_percent (default 20%):
  → Force-stop Roblox: adb shell am force-stop com.roblox.client
  → Sleep screen: KEYCODE_SLEEP
  → Set worker state = BATTERY_SLEEP
  → Poll battery every 60 seconds (lightweight ADB call only)

>= battery_resume_percent (default 80%):
  → Wake device: KEYCODE_WAKEUP
  → Wait 10s for device to settle
  → Launch Roblox
  → Rejoin lead's tank via private_server_link
  → Resume normal loop
```

### 11.2 Temperature Management

```
Poll: adb shell cat /sys/class/thermal/thermal_zone*/temp
Take the maximum reading across all zones.

> temp_throttle_celsius (default 45°C):
  → Double the scan_interval for this device
  → Log warning to UI

> temp_pause_celsius (default 52°C):
  → Pause bot loop entirely
  → Sleep screen: KEYCODE_SLEEP
  → Set worker state = TEMP_PAUSE
  → Poll temp every 30 seconds

< temp_resume_celsius (default 40°C) while in TEMP_PAUSE:
  → Wake device: KEYCODE_WAKEUP
  → Restore normal scan_interval
  → Resume normal loop
```

### 11.3 ADB Connection Watchdog

```
On each loop iteration, if any ADB command returns an error:
  → Mark device as ADB_DISCONNECTED
  → Skip capture and action steps for this iteration
  → Attempt: adb reconnect {serial}
  → Retry every adb_reconnect_interval_s (default 10s)
  → On successful reconnect: resume loop, log recovery
  → UI shows device row in error state (red) during disconnect
```

### 11.4 Health Status Object

Each worker exposes a `HealthStatus` dataclass the UI polls every 500ms:

```python
@dataclass
class HealthStatus:
    serial: str
    battery_percent: int
    temperature_celsius: float
    adb_connected: bool
    worker_state: str       # RUNNING, BATTERY_SLEEP, TEMP_PAUSE, ADB_DISCONNECTED
    last_updated: float     # unix timestamp
```

---

## 12. Crash Detection & Recovery

### 12.1 What Counts as a Crash

| Condition | Detection Method |
|---|---|
| Roblox process not running | `adb shell pidof com.roblox.client` returns empty |
| Roblox home screen visible | Template match: `roblox_home_screen` detector |
| Kicked from tank | State = `LOBBY` for longer than a configurable threshold |
| Game unresponsive | State = `UNKNOWN` for longer than a configurable threshold |

### 12.2 Recovery Sequence

```
1. Detect crash condition
2. Set worker state = CRASHED
3. Force-stop Roblox if still running:
   adb shell am force-stop com.roblox.client
4. Wait 3 seconds
5. Launch Roblox: launch_roblox(serial)
6. Poll for lobby_screen state (timeout 60s)
7. Rejoin tank:
   - Lead device  → join_server_by_link(serial, own private_server_link)
   - Support device → join_server_by_link(serial, lead_device.private_server_link)
8. Poll for IN_RUN state (timeout 60s)
9. Resume normal loop
```

### 12.3 Private Server Rejoin — How It Works

Each Roblox private server has a permanent shareable link containing a
`privateServerLinkCode`. This link does not change unless the server is deleted.

The link is stored in **global settings** (`settings.json`) under
`"private_server_link"`. It is configurable via the Global Settings dialog
in the GUI — no code changes needed to update it.

All devices — lead and support — read the link from `settings.json` at
rejoin time. This means support devices can continue rejoining the private
tank even if the lead device is offline, has hardware issues, or is disabled.
The tank belongs to you, not to any single device.

If the lead is recovering, support devices rejoin independently using the
same stored link. They do not wait for the lead.

**To update the server link:** open Global Settings, paste the new link into
the "Private Server Link" field, and save. All devices pick it up on their
next rejoin attempt.

---

## 13. Auto-Farm Reset Logic

Prevents the 20-minute in-game auto-rejoin timer from kicking devices out of the tank.

**Mechanism:** Double-tap the auto-farm button to turn it off then back on,
resetting the internal timer.

**Configuration:** Per-device timer, default from profile, overridable in GUI.

```
Timer fires every auto_farm_reset_interval_min minutes:
  1. Detect auto_button_on → get click target (center + offset)
  2. Double-tap that target
  3. Wait 500ms
  4. Verify state returned to IN_RUN
  5. Reset timer
```

**Conflict prevention:** A simple per-device lock ensures the auto-farm reset
and end-run reset cannot fire simultaneously. If both timers align, end-run
reset takes priority and the auto-farm reset timer is deferred by 60 seconds.

---

## 14. End-Run Reset Logic

Intentionally ends the run to keep device size small and net collection efficient.
Larger fish = slower movement = lower throughput. Regular resets maintain efficiency.

**Configuration:** Per-device, GUI-adjustable at runtime. Saved to `devices.json`.

### 14.1 Normal End-Run Reset

```
Timer fires every end_run_reset_interval_min minutes:
  1. Detect end_run_button → get click target
  2. Tap to end the run
  3. Poll for DEAD or LOBBY state
  4. Navigate back to IN_RUN (tap through post-death/lobby screens)
  5. Reset timer
```

### 14.2 Cascade Reset (Support Devices)

When the lead resets, support devices reset shortly after to prevent them
from growing large and disrupting the lead's recovery.

```
Lead fires end-run reset:
  → Broadcasts cascade_reset event to all support queues via FarmEventBus
  → Each support worker reads the event at the top of its next loop
  → Waits cascade_reset_delay_after_lead_s (default 30s, profile-configurable)
  → Executes its own end-run reset sequence
```

### 14.3 GUI Timer Controls

The device settings dialog shows two adjustable timers per device:
- **Auto-Farm Reset:** spinbox, in minutes, live-adjustable, saved on change
- **End-Run Reset:** spinbox, in minutes, live-adjustable, saved on change

The main device panel shows a compact version: next-fire countdown for each timer.

---

## 15. Lead-Eaten Detection

Detects when the lead device was eaten by one of the support devices
and triggers an end-run on the responsible device.

### 15.1 Detection Flow (Lead Private Only)

```
State transitions to DEAD:
  1. Capture death screen frame
  2. For each support device:
     a. Load that device's eaten_by_name.png from assets/devices/{serial}/
     b. Template match against the death screen frame
     c. If match score >= threshold:
        → Identify this device as the eater
        → Post force_end_run event to that device's queue via FarmEventBus
        → Log the event with device nickname and confidence score
        → Stop checking other devices (only one eater possible)
  3. Lead proceeds with its normal death recovery sequence regardless
```

### 15.2 Per-Device Name Images

Each device has its character's in-game name saved as it appears on another
player's death screen. Captured once using the Image Capture Tool.

Path: `assets/devices/{serial}/eaten_by_name.png`

This image is always device-specific and is never shared.

### 15.3 Public Mode (Lead Public — Phase 2)

On death in public mode: save the full death screen frame to
`debug_shots/eaten_by/{timestamp}.png` for manual review. No logic action.

---

## 16. UI Structure

Tkinter application. Runs minimized by default. The core device loops run
regardless of UI visibility. UI only reads from workers — it never writes
directly to device state. All config changes go through `devices.json`
or `FarmEventBus`.

### 16.1 Main Window Layout

```
┌──────────────────────────────────────────────────────┐
│  Be Fish Farm Manager                 [─] [□] [✕]    │
├──────────────────────────────────────────────────────┤
│  [Start All]  [Stop All]  [Settings]                  │
├──────────────────────────────────────────────────────┤
│  DEVICES                                             │
│  ┌────────────────────────────────────────────────┐  │
│  │ ★ Pixel 7 Alpha  LEAD  IN_RUN  🔋78%  41°C     │  │
│  │   [On/Off]  [Settings]  [End Run Now]           │  │
│  │   Auto reset: 12:34 remaining                  │  │
│  │   End run:   04:17 remaining                   │  │
│  ├────────────────────────────────────────────────┤  │
│  │   Pixel 6 Beta   SUPP  IN_RUN  🔋91%  39°C     │  │
│  │   [On/Off]  [Settings]  [End Run Now]           │  │
│  │   Auto reset: 08:02 remaining                  │  │
│  │   End run:   07:44 remaining                   │  │
│  ├────────────────────────────────────────────────┤  │
│  │   Pixel 6 Gamma  SUPP  DEAD    🔋65%  43°C     │  │
│  │   [On/Off]  [Settings]  [End Run Now]           │  │
│  └────────────────────────────────────────────────┘  │
├──────────────────────────────────────────────────────┤
│  LOG                                                 │
│  [scrolled text, last 200 lines, per-device filter]  │
│  [Filter: ________]  [Clear]                         │
└──────────────────────────────────────────────────────┘
```

### 16.2 Device Settings Dialog

Opens via [Settings] on any device row. Contains:

- Nickname and notes fields
- Profile selector (lead_private / support_private / lead_public / support_public)
- **Is Lead** toggle — selecting this de-selects all other devices. Enforced to max 1.
- Capture backend selector: Scrcpy Socket (default) / ADB Screencap (fallback)
- Auto-Farm Reset interval spinbox (minutes)
- End-Run Reset interval spinbox (minutes)
- Scan interval override (ms)
- Detector list — shows each detector name, image path, and click offset.
  Click offset editable inline. Image path is read-only (use Image Capture Tool to change).
- [Open Image Capture Tool] button
- [Save]  [Cancel]

### 16.3 Global Settings Dialog

- ADB executable path
- **Private Server Link** — paste your Roblox private server URL here.
  Used by all devices (lead and support) when rejoining the private tank.
  Stored in `settings.json`. Update here if you switch servers.
- Default template confidence threshold
- Default capture backend (Scrcpy Socket / ADB Screencap)
- Health thresholds: battery min %, battery resume %, temp throttle °C,
  temp pause °C, temp resume °C
- ADB reconnect interval (seconds)
- Debug options: save failed captures, log state changes, screenshot directory
- [Save]  [Cancel]

### 16.4 UI Refresh

UI polls all worker `HealthStatus` objects every 500ms via `root.after()`.
Workers never touch Tkinter directly. All UI updates happen on the main thread
through polling. No callbacks cross the thread boundary.

---

## 17. Phase Plan

### Phase 1 — Core Private Mode *(Build This First)*

- [ ] Project skeleton and package structure
- [ ] `settings.json` and `devices.json` read/write with validation
- [ ] YAML profile loader
- [ ] ADB device discovery and connection management (`DeviceManager`)
- [ ] `CaptureBackend` abstraction
- [ ] `ScrcpySocketBackend` (primary capture backend)
- [ ] `ADBScreencapBackend` (fallback capture backend)
- [ ] Per-device capture backend selector in device settings
- [ ] `TemplateBank` with shared/device-specific image resolution
- [ ] `DetectorEngine` (OpenCV TM_CCOEFF_NORMED) + `DetectResult`
- [ ] Click target resolution (center + offset)
- [ ] `StateMachine` with private profile rule sets
- [ ] `FarmEventBus` for inter-device signaling
- [ ] `DeviceWorker` thread loop
- [ ] ADB input actions (`actions.py`)
- [ ] Health monitor (battery, temperature, ADB watchdog)
- [ ] Crash detection and recovery sequence
- [ ] Private server rejoin via deep link (`join_server_by_link`)
- [ ] Auto-farm reset timer
- [ ] End-run reset timer (per device, GUI-adjustable)
- [ ] Cascade reset broadcast on lead end-run
- [ ] Lead-eaten detection → trigger support end-run via FarmEventBus
- [ ] Image Capture & Crop Tool (guided wizard, test button)
- [ ] Basic Tkinter UI (device list, status rows, timer countdowns, log)
- [ ] Device settings dialog
- [ ] Global settings dialog (including Private Server Link field)

### Phase 2 — Scrcpy Viewer Windows

- [ ] On-demand per-device scrcpy viewer panel
- [ ] Launch/kill scrcpy process per device toggle
- [ ] `viewer_pid` slot in `DeviceWorker` (hook already reserved in Phase 1)

### Phase 3 — Public Mode

- [ ] Lead Public profile logic
- [ ] Support Public profile logic
- [ ] Public server joining flow
- [ ] Eaten-by screenshot saving for public lead

### Phase 4 — Advanced Device Management

- [ ] Stripped device / phone bank setup tooling
- [ ] Remote status dashboard
- [ ] Multi-hub support

---

## 18. Key Principles

**Separation of concerns:**
Capture, detection, state resolution, and action are four independent layers.
Each can be changed or replaced without touching the others.

**Configuration placement:**
- Can this vary per device? → `devices.json`
- Is this global to the app? → `settings.json`
- Does this describe behavior or logic flow? → YAML profile

**Startup never blocks the UI:**
Missing images, disconnected devices, and validation warnings surface in the UI
as warnings, not fatal exits. The UI is the fix mechanism.

**Workers are isolated:**
Each device worker thread knows only about its own device. Inter-device
communication goes exclusively through `FarmEventBus`. No shared mutable
state between workers outside the bus.

**Capture backend is swappable:**
All capture code goes through `CaptureBackend.get_frame()`. Scrcpy socket is
the primary backend. ADB screencap is the fallback. Switching per device is a
one-line change at instantiation, selectable from the device settings dialog.

**Coordinates come from detection:**
Click targets are derived from detected image centers at runtime, not from
manually entered absolute coordinates. The `click_offset` in `devices.json`
is a fine-tuning delta, not a primary coordinate source. Recapturing a
detection image resets its offset to `[0, 0]`.

**Images can be shared or per-device:**
Shared detection images live in `assets/shared/`. Per-device overrides live
in `assets/devices/{serial}/`. The `TemplateBank` resolves which to use.
The Image Capture Tool manages this automatically.

**UI never writes to worker state directly:**
UI reads via polling. UI writes go through `devices.json` (config changes)
or `FarmEventBus` (runtime signals). No direct method calls from the UI
thread into worker thread state.

**Private server link is global config, not device config:**
The Roblox private server URL lives in `settings.json` and is editable from
the Global Settings dialog. All devices — lead and support — read from the same
source. Support devices can rejoin the private tank independently even if the
lead device is offline. No code changes needed to switch servers.

---

*End of Plan — Be Fish Farm Manager v1*  
*Status: Final — All decisions made, ready to begin Phase 1 implementation*
