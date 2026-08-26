"""
detection/result.py

DetectResult dataclass — the output of every detector run.

Every detector returns one of these regardless of whether the target was found.
The worker loop and state machine read from these to determine state and actions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass
class DetectResult:
    """
    Result of running one detector against one frame.

    Attributes:
        name        : detector name (e.g. "auto_button_on")
        found       : True if the template was matched above threshold
        bbox        : (x, y, w, h) of the matched region in screen coords, or None
        center      : (cx, cy) center of the matched region, or None
        score       : match confidence score (0.0 - 1.0), or None if not found
        matched_path: which template image file produced the best match
    """
    name: str
    found: bool
    bbox: Optional[Tuple[int, int, int, int]] = None   # (x, y, w, h)
    center: Optional[Tuple[int, int]] = None            # (cx, cy)
    score: Optional[float] = None
    matched_path: Optional[str] = None

    @classmethod
    def not_found(cls, name: str) -> "DetectResult":
        """Convenience constructor for a clean not-found result."""
        return cls(name=name, found=False)

    def click_target(self, offset: Tuple[int, int] = (0, 0)) -> Optional[Tuple[int, int]]:
        """
        Resolve the ADB tap coordinate for this detection result.

        Args:
            offset: (dx, dy) pixels from center to shift the tap target.
                    Comes from device config: detector.click_offset.
                    [0, 0] = tap dead center of the detected image.

        Returns:
            (x, y) in screen-absolute coordinates, or None if not found.
        """
        if not self.found or self.center is None:
            return None
        cx, cy = self.center
        dx, dy = offset
        return (cx + dx, cy + dy)
