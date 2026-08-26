"""
bot/actions.py

All ADB input actions.

Every interaction with a device goes through this module.
All coordinates are screen-absolute (ADB input tap uses screen coords).

Click targets are resolved by the worker from DetectResult.click_target(offset),
then passed here as plain (x, y) tuples.
"""

from __future__ import annotations

import subprocess
import time
from typing import Optional, Tuple


def _adb(adb_path: str, serial: str, *args, timeout: float = 10.0) -> subprocess.CompletedProcess:
    """Run an ADB shell command for a specific device."""
    cmd = [adb_path, "-s", serial] + list(args)
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


# ---------------------------------------------------------------------------
# Touch input
# ---------------------------------------------------------------------------

def tap(serial: str, x: int, y: int, adb_path: str = "adb") -> None:
    """Send a single tap at screen coordinates (x, y)."""
    _adb(adb_path, serial, "shell", "input", "tap", str(x), str(y))


def double_tap(
    serial: str,
    x: int,
    y: int,
    interval_ms: int = 150,
    adb_path: str = "adb",
) -> None:
    """
    Send two taps in quick succession at (x, y).
    Used for auto-farm reset: double-tap the auto button to toggle off then on.

    Args:
        interval_ms: milliseconds between the two taps (default 150ms)
    """
    tap(serial, x, y, adb_path)
    time.sleep(interval_ms / 1000.0)
    tap(serial, x, y, adb_path)


def swipe(
    serial: str,
    x1: int, y1: int,
    x2: int, y2: int,
    duration_ms: int = 200,
    adb_path: str = "adb",
) -> None:
    """Send a swipe gesture from (x1, y1) to (x2, y2)."""
    _adb(
        adb_path, serial,
        "shell", "input", "swipe",
        str(x1), str(y1), str(x2), str(y2), str(duration_ms),
    )


# ---------------------------------------------------------------------------
# Key events
# ---------------------------------------------------------------------------

def key_event(serial: str, keycode: int, adb_path: str = "adb") -> None:
    """Send an Android key event by keycode."""
    _adb(adb_path, serial, "shell", "input", "keyevent", str(keycode))


def wake_device(serial: str, adb_path: str = "adb") -> None:
    """Wake the device screen (KEYCODE_WAKEUP = 224)."""
    key_event(serial, 224, adb_path)


def sleep_device(serial: str, adb_path: str = "adb") -> None:
    """Turn the device screen off (KEYCODE_SLEEP = 223)."""
    key_event(serial, 223, adb_path)


def press_back(serial: str, adb_path: str = "adb") -> None:
    """Press the Android back button (KEYCODE_BACK = 4)."""
    key_event(serial, 4, adb_path)


def press_home(serial: str, adb_path: str = "adb") -> None:
    """Press the Android home button (KEYCODE_HOME = 3)."""
    key_event(serial, 3, adb_path)


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

def launch_roblox(
    serial: str,
    adb_path: str = "adb",
    package: str = "com.roblox.client",
) -> bool:
    """
    Launch Roblox to its main screen using the monkey launcher.
    Returns True if the command succeeded (does not guarantee the app loaded).
    """
    result = _adb(
        adb_path, serial,
        "shell", "monkey",
        "-p", package,
        "-c", "android.intent.category.LAUNCHER",
        "1",
        timeout=15.0,
    )
    return result.returncode == 0


def force_stop_roblox(
    serial: str,
    adb_path: str = "adb",
    package: str = "com.roblox.client",
) -> None:
    """Force-stop Roblox. Use before relaunch to ensure a clean start."""
    _adb(adb_path, serial, "shell", "am", "force-stop", package)


def join_server_by_link(
    serial: str,
    link: str,
    adb_path: str = "adb",
    package: str = "com.roblox.client",
) -> bool:
    """
    Launch Roblox directly into a private server using the deep link URL.

    The link is the Roblox private server share URL, stored in settings.json
    under "private_server_link". It looks like:
      https://www.roblox.com/games/XXXXXXXXX?privateServerLinkCode=YYYYY...

    Android handles this via an intent VIEW action. Roblox intercepts the
    URL and joins the specified server directly.

    Returns True if the ADB command succeeded.
    """
    if not link:
        return False

    result = _adb(
        adb_path, serial,
        "shell", "am", "start",
        "-a", "android.intent.action.VIEW",
        "-d", link,
        package,
        timeout=15.0,
    )
    return result.returncode == 0


def is_roblox_running(
    serial: str,
    adb_path: str = "adb",
    package: str = "com.roblox.client",
) -> bool:
    """
    Check if the Roblox process is running on the device.
    Uses pidof to check for the process.
    """
    try:
        result = _adb(adb_path, serial, "shell", "pidof", package, timeout=5.0)
        return bool(result.stdout.strip())
    except Exception:
        return False


def get_foreground_app(serial: str, adb_path: str = "adb") -> Optional[str]:
    """
    Return the package name of the currently foreground app, or None.
    Useful for detecting if Roblox was backgrounded or replaced by another app.
    """
    try:
        result = _adb(
            adb_path, serial,
            "shell", "dumpsys", "activity",
            "activities", "|", "grep", "mResumedActivity",
            timeout=5.0,
        )
        output = result.stdout.decode("utf-8", errors="replace")
        # Output format: "mResumedActivity: ActivityRecord{... package/component ...}"
        if "mResumedActivity" in output:
            # Extract the package name from the activity record
            parts = output.strip().split()
            for part in parts:
                if "/" in part and "." in part:
                    return part.split("/")[0]
        return None
    except Exception:
        return None
