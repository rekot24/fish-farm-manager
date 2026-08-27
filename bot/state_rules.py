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
If no rule matches, STATE_UNKNOWN is returned.

Important: do not add a catch-all LOADING rule with an empty require_all list.
That would prevent STATE_UNKNOWN from ever being reached and would disable the
worker's UNKNOWN timeout/crash-recovery path. Add LOADING only when there is an
affirmative detector that proves a loading screen is visible.
"""

from typing import Dict, List


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
]


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


STATE_RULES: Dict[str, List[Dict]] = {
    "lead_private": _PRIVATE_RULES,
    "support_private": _PRIVATE_RULES,
    "lead_public": _PUBLIC_RULES,
    "support_public": _PUBLIC_RULES,
}
