"""
bot/state_rules.py

State detection rules for each profile.

Rule format:
  state        : the state string this rule resolves to
  require_all  : all of these detectors must be found (found=True)
  require_none : none of these detectors may be found
  priority     : higher priority rules are checked first

Rules are evaluated in descending priority order.
The first matching rule wins.
If no rule matches, STATE_UNKNOWN is returned by the state machine.

UNKNOWN is the correct fallback — do not add catch-all rules with empty
require_all, as they prevent the crash-recovery timeout from triggering.
"""

from typing import Dict, List

# ---------------------------------------------------------------------------
# Private mode rules (shared between lead_private and support_private)
# ---------------------------------------------------------------------------

_PRIVATE_RULES: List[Dict] = [
    {
        "state": "DEAD",
        "require_all": ["death_screen"],
        "require_none": [],
        "priority": 100,
    },
    {
        "state": "IN_RUN",
        "require_all": ["in_run_indicator"],
        "require_none": ["death_screen"],
        "priority": 80,
    },
    {
        "state": "LOBBY",
        "require_all": ["lobby_screen"],
        "require_none": ["in_run_indicator", "death_screen"],
        "priority": 60,
    },
    # No catch-all rule — unmatched states fall through to STATE_UNKNOWN,
    # which allows the 60-second crash-recovery timeout to trigger.
]

# ---------------------------------------------------------------------------
# Public mode rules (shared between lead_public and support_public)
# ---------------------------------------------------------------------------

_PUBLIC_RULES: List[Dict] = [
    {
        "state": "DEAD",
        "require_all": ["death_screen"],
        "require_none": [],
        "priority": 100,
    },
    {
        "state": "IN_RUN",
        "require_all": ["in_run_indicator"],
        "require_none": ["death_screen"],
        "priority": 80,
    },
    {
        "state": "LOBBY",
        "require_all": ["lobby_screen"],
        "require_none": ["in_run_indicator", "death_screen"],
        "priority": 60,
    },
]

# ---------------------------------------------------------------------------
# Rule registry by profile name
# ---------------------------------------------------------------------------

STATE_RULES: Dict[str, List[Dict]] = {
    "lead_private":    _PRIVATE_RULES,
    "support_private": _PRIVATE_RULES,
    "lead_public":     _PUBLIC_RULES,
    "support_public":  _PUBLIC_RULES,
}
