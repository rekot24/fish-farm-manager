"""
bot/state_machine.py

Resolves a single state string from a dict of DetectResults.

Usage:
    state = resolve_state(results, profile="support_private")

The result dict maps detector_name -> DetectResult.
Rules are evaluated in descending priority order (highest first).
First matching rule wins. Falls back to STATE_UNKNOWN if nothing matches.
"""

from __future__ import annotations

from typing import Dict

from detection.result import DetectResult
from bot.state_rules import STATE_RULES
from bot.states import STATE_UNKNOWN


def resolve_state(
    results: Dict[str, DetectResult],
    profile: str,
) -> str:
    """
    Evaluate state rules for the given profile against detector results.

    Args:
        results : dict of detector_name -> DetectResult from the current scan
        profile : profile name (e.g. "support_private") — selects which rule set to use

    Returns:
        A state string constant from bot.states, or STATE_UNKNOWN if no rule matches.
    """
    rules = STATE_RULES.get(profile)
    if not rules:
        # Unknown profile — return unknown rather than crashing
        return STATE_UNKNOWN

    # Sort by priority descending — highest priority checked first
    sorted_rules = sorted(rules, key=lambda r: r.get("priority", 0), reverse=True)

    for rule in sorted_rules:
        require_all  = rule.get("require_all", [])
        require_none = rule.get("require_none", [])

        # All required detectors must be found
        all_found = all(
            results.get(name) is not None and results[name].found
            for name in require_all
        )

        # None of the excluded detectors may be found
        none_found = all(
            results.get(name) is None or not results[name].found
            for name in require_none
        )

        if all_found and none_found:
            return rule["state"]

    return STATE_UNKNOWN
