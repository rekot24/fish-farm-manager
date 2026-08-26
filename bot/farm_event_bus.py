"""
bot/farm_event_bus.py

FarmEventBus — thread-safe inter-device signaling.

The lead device posts events (cascade_reset, force_end_run) that support
device workers read at the top of their next loop iteration.

Design:
  - One queue per device serial
  - Lead posts to a specific device or broadcasts to all
  - Workers poll (non-blocking) at the start of each loop
  - Events are simple dicts: {"type": "...", ...}

Thread safety:
  - queue.Queue is thread-safe for put/get
  - Device registration (add_device) should happen before workers start

Event types:
  cascade_reset   : lead finished an end-run, support should reset soon
  force_end_run   : support device ate the lead, end run immediately
"""

from __future__ import annotations

import queue
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------

EVENT_CASCADE_RESET = "cascade_reset"
EVENT_FORCE_END_RUN = "force_end_run"


class FarmEventBus:
    """
    Simple per-device event queue.

    One shared instance is created by DeviceManager and passed to all workers.
    """

    def __init__(self):
        # serial -> queue.Queue of event dicts
        self._queues: Dict[str, queue.Queue] = {}

    def register(self, serial: str) -> None:
        """
        Register a device serial with the bus.
        Must be called before the device's worker starts.
        """
        if serial not in self._queues:
            self._queues[serial] = queue.Queue()

    def unregister(self, serial: str) -> None:
        """Remove a device from the bus (called when device disconnects)."""
        self._queues.pop(serial, None)

    def post(self, target_serial: str, event: dict) -> None:
        """
        Post an event to a specific device's queue.
        Silently ignored if the target serial is not registered.
        """
        q = self._queues.get(target_serial)
        if q is not None:
            q.put(event)

    def broadcast(self, event: dict, exclude_serial: Optional[str] = None) -> None:
        """
        Post an event to all registered devices except the excluded one.
        Typically called by the lead to signal all support devices.

        Args:
            event          : the event dict to broadcast
            exclude_serial : serial to skip (usually the lead's own serial)
        """
        for serial, q in self._queues.items():
            if serial != exclude_serial:
                q.put(event)

    def poll(self, serial: str) -> Optional[dict]:
        """
        Non-blocking poll for the next event for a device.
        Returns the event dict, or None if the queue is empty.

        Called at the top of each worker loop iteration.
        """
        q = self._queues.get(serial)
        if q is None:
            return None
        try:
            return q.get_nowait()
        except queue.Empty:
            return None

    def poll_all(self, serial: str) -> List[dict]:
        """
        Drain all pending events for a device in one call.
        Useful if multiple events may have queued up between loop iterations.
        """
        q = self._queues.get(serial)
        if q is None:
            return []

        events = []
        while True:
            try:
                events.append(q.get_nowait())
            except queue.Empty:
                break
        return events

    def registered_serials(self) -> List[str]:
        """Return list of all registered device serials."""
        return list(self._queues.keys())
