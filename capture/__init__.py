"""
capture/__init__.py

Factory function for instantiating the correct CaptureBackend
based on the device's capture_backend setting.

Usage:
    from capture import make_backend
    backend = make_backend(serial="XXXX", backend_type="scrcpy", adb_path="adb")
    backend.connect()
    frame = backend.get_frame()
"""

from capture.base import CaptureBackend
from capture.adb_screencap import ADBScreencapBackend
from capture.scrcpy_socket import ScrcpySocketBackend


def make_backend(
    serial: str,
    backend_type: str = "scrcpy",
    adb_path: str = "adb",
    **kwargs,
) -> CaptureBackend:
    """
    Instantiate the correct CaptureBackend for a device.

    Args:
        serial       : ADB device serial
        backend_type : "scrcpy" (default/primary) or "adb" (fallback)
        adb_path     : path to adb executable
        **kwargs     : passed through to the backend constructor

    Returns:
        A CaptureBackend instance (not yet connected — call connect() separately).

    Raises:
        ValueError if backend_type is unknown.
    """
    if backend_type == "scrcpy":
        return ScrcpySocketBackend(serial=serial, adb_path=adb_path, **kwargs)
    elif backend_type == "adb":
        return ADBScreencapBackend(serial=serial, adb_path=adb_path, **kwargs)
    else:
        raise ValueError(
            f"Unknown capture backend type: '{backend_type}'. "
            f"Valid options: 'scrcpy', 'adb'"
        )
