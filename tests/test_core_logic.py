"""Regression tests for state resolution and inter-device event delivery.

Run from the repository root with:
    python -m unittest discover -s tests -v
"""

import unittest

from bot.farm_event_bus import FarmEventBus, EVENT_CASCADE_RESET, EVENT_FORCE_END_RUN
from bot.state_machine import resolve_state
from detection.result import DetectResult


def found(name: str) -> DetectResult:
    return DetectResult(
        name=name,
        found=True,
        bbox=(0, 0, 10, 10),
        center=(5, 5),
        score=1.0,
        matched_path=f"{name}.png",
    )


def missing(name: str) -> DetectResult:
    return DetectResult.not_found(name)


class StateMachineTests(unittest.TestCase):
    def test_private_in_run(self):
        results = {
            "in_run_indicator": found("in_run_indicator"),
            "death_screen": missing("death_screen"),
            "lobby_screen": missing("lobby_screen"),
        }
        self.assertEqual(resolve_state(results, "lead_private"), "IN_RUN")

    def test_death_has_priority_over_in_run(self):
        results = {
            "in_run_indicator": found("in_run_indicator"),
            "death_screen": found("death_screen"),
            "lobby_screen": missing("lobby_screen"),
        }
        self.assertEqual(resolve_state(results, "support_private"), "DEAD")

    def test_no_match_returns_unknown_for_crash_timeout(self):
        results = {
            "in_run_indicator": missing("in_run_indicator"),
            "death_screen": missing("death_screen"),
            "lobby_screen": missing("lobby_screen"),
        }
        self.assertEqual(resolve_state(results, "lead_private"), "UNKNOWN")

    def test_unknown_profile_returns_unknown(self):
        self.assertEqual(resolve_state({}, "not_a_profile"), "UNKNOWN")


class EventBusTests(unittest.TestCase):
    def test_targeted_event_only_reaches_target(self):
        bus = FarmEventBus()
        bus.register("lead")
        bus.register("support")

        bus.post("support", {"type": EVENT_FORCE_END_RUN})

        self.assertEqual(bus.poll_all("lead"), [])
        self.assertEqual(
            bus.poll_all("support"),
            [{"type": EVENT_FORCE_END_RUN}],
        )

    def test_broadcast_excludes_lead(self):
        bus = FarmEventBus()
        bus.register("lead")
        bus.register("support-a")
        bus.register("support-b")

        event = {"type": EVENT_CASCADE_RESET, "delay_s": 30}
        bus.broadcast(event, exclude_serial="lead")

        self.assertEqual(bus.poll_all("lead"), [])
        self.assertEqual(bus.poll_all("support-a"), [event])
        self.assertEqual(bus.poll_all("support-b"), [event])

    def test_unregister_discards_old_queue(self):
        bus = FarmEventBus()
        bus.register("support")
        bus.post("support", {"type": EVENT_FORCE_END_RUN})
        bus.unregister("support")
        bus.register("support")

        self.assertEqual(bus.poll_all("support"), [])


if __name__ == "__main__":
    unittest.main()
