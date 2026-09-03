"""
config/constants.py

Every named value in this app that would otherwise be a bare literal
sitting in the middle of logic code (CLAUDE.md standing instruction 5).

Two kinds of constant live here, and every one is tagged as one or the
other in its comment:

  [TUNABLE] — a user-adjustable value. It will (eventually) be exposed in
              the settings UI and overridable through the settings store
              (see ROADMAP.md Phase 12). The constant here is the default.
              Where a live config field already exists for it (HealthConfig,
              AdbConfig — see config/settings.py), that field's default
              references the constant below rather than repeating the
              literal a second time.

  [INTERNAL] — an implementation fact. It needs a name so it isn't a bare
               literal, but it has no meaningful user-facing context and
               will never surface in a settings UI.

UI layout constants (pixel sizes, row heights, widget counts) are the one
exception — those live as module-level constants at the top of the UI file
that uses them, not here. They're facts about one screen's rendering, not
app configuration.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# ADB command timeouts
#
# Three genuinely different tiers, not one shared value: a quick status
# check, a typical shell/input command, and a slower app-launch/deep-link
# intent each tolerate different amounts of latency. Collapsing them to one
# constant would quietly change how patient each kind of call is.
# ---------------------------------------------------------------------------

# [TUNABLE] Quick status checks: get-state, pidof, dumpsys battery.
ADB_QUICK_TIMEOUT_S = 5.0

# [TUNABLE] Typical adb shell / input commands (taps, key events, most
# subprocess calls). The general-purpose default.
ADB_DEFAULT_TIMEOUT_S = 10.0

# [TUNABLE] App launch / deep-link intents (monkey, am start) — slower to
# respond than a plain shell command.
ADB_LAUNCH_TIMEOUT_S = 15.0

# [TUNABLE] `adb exec-out screencap -p` in the ADB-screencap capture backend.
ADB_SCREENCAP_TIMEOUT_S = 8.0

# [TUNABLE] Screencap timeout used by the Image Capture Tool's "test all
# selected devices" batch flow — separate from ADB_SCREENCAP_TIMEOUT_S since
# it's a different call site that happened to already use a different value;
# kept distinct rather than merged so tuning one doesn't silently affect the
# other.
ADB_SCREENCAP_BATCH_TIMEOUT_S = 15.0

# [TUNABLE] Pause after `adb reconnect` before re-checking connection state,
# to give the device a moment to re-enumerate over USB.
ADB_RECONNECT_SETTLE_S = 2.0


# ---------------------------------------------------------------------------
# Device recovery / health timing (device_worker.py)
#
# How long the worker waits at each step of crash recovery, battery sleep,
# and thermal pause. Genuinely tunable — the active farm spans a Pixel 3
# (Snapdragon 845, 2018) to a Pixel 8a, and slower devices may need more
# settle time than these defaults assume.
# ---------------------------------------------------------------------------

# [TUNABLE] How long a device can sit in STATE_UNKNOWN before the worker
# treats it as crashed and force-restarts Roblox.
CRASH_DETECT_AFTER_S = 60.0

# [TUNABLE] Pause after force-stopping Roblox, before relaunching it, during
# crash recovery — gives Android a moment to fully tear down the process.
CRASH_RECOVERY_SETTLE_S = 3.0

# [TUNABLE] Pause after force-stopping Roblox, before sending the screen-off
# key event, when entering battery sleep.
BATTERY_SLEEP_SETTLE_S = 1.0

# [TUNABLE] How often to re-check battery level while a device is sleeping
# for low battery.
BATTERY_SLEEP_POLL_S = 60.0

# [TUNABLE] Pause after waking a device (battery recovered), before
# relaunching Roblox — gives the screen/system a moment to come back up.
WAKE_SETTLE_S = 10.0

# [TUNABLE] How often to re-check temperature while a device is paused for
# overheating.
TEMP_PAUSE_POLL_S = 30.0

# [TUNABLE] Scan-interval multiplier applied while a device is temperature-
# throttled but not yet critical — e.g. 2.0 doubles the interval, scanning
# half as often to generate less heat.
THERMAL_THROTTLE_MULTIPLIER = 2.0

# [INTERNAL] How long DeviceWorker.stop() waits for the worker thread to
# exit cleanly before giving up. Not user-meaningful — there's no good
# reason to want this longer or shorter.
WORKER_JOIN_TIMEOUT_S = 5.0

# [INTERNAL] Minimum floor on the worker loop's sleep between iterations,
# so a very fast iteration (elapsed ~= 0) never busy-loops.
LOOP_SLEEP_FLOOR_S = 0.05


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

# [TUNABLE] Default minimum template-match score (0.0-1.0) to count a
# detector as "found". Single source for both Settings.template_confidence_
# default and detection/detector.py's function defaults — previously
# duplicated as a bare 0.82 in five separate places.
DEFAULT_TEMPLATE_CONFIDENCE = 0.82


# ---------------------------------------------------------------------------
# Health monitor — temperature parsing heuristics (health_monitor.py)
#
# Facts about how Android reports /sys/class/thermal/thermal_zone*/temp,
# not something a user would ever want to change.
# ---------------------------------------------------------------------------

# [INTERNAL] Values above this are in millidegrees Celsius and need
# dividing by 1000; at or below, they're already in whole degrees.
THERMAL_MILLIDEGREE_CUTOFF = 1000

# [INTERNAL] Sanity bounds on a parsed temperature reading — values outside
# this range are treated as bad data and ignored, not as a real reading.
MIN_PLAUSIBLE_TEMP_C = 0
MAX_PLAUSIBLE_TEMP_C = 120


# ---------------------------------------------------------------------------
# Device behavior (config/devices.py's TimerConfig) — moved off profile YAML
# in Phase 6 (see AUDIT.md / ROADMAP.md), where this was a bare `30` default
# already baked into the Python code (`cascade_cfg.get("delay_after_lead_s",
# 30)`) rather than the value the (unused) YAML block claimed to set.
# ---------------------------------------------------------------------------

# [TUNABLE] How long a support device waits after receiving a cascade-reset
# signal from the lead before firing its own end-run.
CASCADE_RESET_DELAY_S = 30.0


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

# [INTERNAL] Unit conversion, not a tuning value.
SECONDS_PER_MINUTE = 60


# ---------------------------------------------------------------------------
# Scrcpy capture backend (capture/scrcpy_socket.py)
#
# Internal implementation details of the socket connection sequence — none
# of these are meaningful to expose to a user; _BASE_PORT, connect_timeout_s,
# _HEADER_SIZE, and _VIDEO_HEADER_SIZE already have clear names where they
# live and aren't duplicated here.
# ---------------------------------------------------------------------------

# [INTERNAL] Size of the local port range spread across by hash(serial) —
# enough for 100 simultaneous devices without collision.
SCRCPY_PORT_RANGE_SIZE = 100

# [TUNABLE] Pause after starting the scrcpy server process on-device, before
# attempting the local socket connection — gives it a moment to bind.
# Left [INTERNAL] rather than wired to a live settings field this phase:
# doing so would mean threading a new parameter through make_backend() and
# DeviceWorker's backend construction for one capture-backend-internal delay
# — more plumbing than this phase's scope. Revisit if it needs tuning.
SCRCPY_SERVER_BIND_SETTLE_S = 0.5

# [INTERNAL] How long to wait for the background decode thread to exit
# cleanly during disconnect().
SCRCPY_DECODE_THREAD_JOIN_TIMEOUT_S = 2.0

# [INTERNAL] Timeout for the two on-device teardown commands during
# disconnect() (killing the scrcpy-server process, removing the port
# forward) — quick cleanup calls, not worth exposing.
SCRCPY_TEARDOWN_TIMEOUT_S = 3.0

# [INTERNAL] Per-attempt timeout for a single socket connect try inside
# _connect_socket()'s retry loop — distinct from connect_timeout_s, which
# bounds the whole retry loop, not one attempt.
SCRCPY_SOCKET_CONNECT_ATTEMPT_TIMEOUT_S = 2.0

# [INTERNAL] Backoff between socket connect retries while the on-device
# server isn't ready yet.
SCRCPY_SOCKET_RETRY_SLEEP_S = 0.2
