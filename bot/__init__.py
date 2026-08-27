"""Be Fish core package initialization.

If this repository contains its own Android Platform Tools installation, put it
at the front of PATH for this Python process. Existing subprocess calls that use
"adb" then resolve to the repo-local executable without requiring a system-wide
ADB installation or PATH configuration.
"""

from __future__ import annotations

import os

from bot.tool_paths import bundled_adb_path


_platform_tools = bundled_adb_path().parent
if _platform_tools.exists():
    current_path = os.environ.get("PATH", "")
    parts = current_path.split(os.pathsep) if current_path else []
    local_tools = str(_platform_tools.resolve())
    if local_tools not in parts:
        os.environ["PATH"] = local_tools + (os.pathsep + current_path if current_path else "")
