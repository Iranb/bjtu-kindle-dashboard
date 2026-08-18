import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "apple_calendar_agenda", ROOT / "scripts" / "apple_calendar_agenda.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AppleCalendarAgendaTests(unittest.TestCase):
    def eventkit_runner(self, payload, returncode=0, stderr=""):
        def runner(command, **kwargs):
            self.assertNotIn("osascript", " ".join(command))
            output = Path(kwargs["env"]["BJTU_CALENDAR_OUTPUT"])
            output.write_text(payload, encoding="utf-8")
            return subprocess.CompletedProcess(command, returncode, "", stderr)

        return runner

    def test_query_returns_only_bounded_minimal_fields(self) -> None:
        now = datetime(2026, 8, 18, 1, 0, tzinfo=timezone.utc)
        rows = [
            {
                "title": "  Group\nmeeting  ",
                "start": (now + timedelta(hours=1)).isoformat(),
                "end": (now + timedelta(hours=2)).isoformat(),
                "all_day": False,
                "location": "must-not-survive",
                "notes": "must-not-survive",
            }
        ]

        agenda = MODULE.query_apple_calendar(
            now=now,
            runner=self.eventkit_runner(json.dumps(rows)),
            helper_executable=ROOT / "scripts/apple_calendar_eventkit.swift",
        )
        self.assertEqual(len(agenda), 1)
        self.assertEqual(set(agenda[0]), {"title", "start", "end", "all_day"})
        self.assertEqual(agenda[0]["title"], "Group meeting")
        self.assertNotIn("must-not-survive", json.dumps(agenda))

    def test_query_failure_does_not_echo_calendar_content(self) -> None:
        with self.assertRaises(MODULE.CalendarError) as raised:
            MODULE.query_apple_calendar(
                runner=self.eventkit_runner(
                    "", returncode=1, stderr="private event title"
                ),
                helper_executable=ROOT / "scripts/apple_calendar_eventkit.swift",
            )
        self.assertNotIn("private event title", str(raised.exception))

    def test_normalizer_deduplicates_and_rejects_outside_window(self) -> None:
        now = datetime(2026, 8, 18, tzinfo=timezone.utc)
        inside = {
            "title": "Inside",
            "start": (now + timedelta(hours=1)).isoformat(),
            "end": (now + timedelta(hours=2)).isoformat(),
            "all_day": False,
        }
        outside = {
            "title": "Outside",
            "start": (now + timedelta(days=2)).isoformat(),
            "end": (now + timedelta(days=2, hours=1)).isoformat(),
            "all_day": False,
        }
        agenda = MODULE.normalize_agenda(
            [inside, inside, outside],
            start=now,
            end=now + timedelta(hours=24),
            max_events=5,
        )
        self.assertEqual([row["title"] for row in agenda], ["Inside"])

    def test_month_range_is_bounded_to_six_weeks(self) -> None:
        start = datetime(2026, 7, 26, tzinfo=timezone.utc)

        self.assertEqual(
            MODULE.query_apple_calendar_range(
                start=start,
                end=start + timedelta(days=42),
                max_events=84,
                runner=self.eventkit_runner("[]"),
                helper_executable=ROOT / "scripts/apple_calendar_eventkit.swift",
            ),
            [],
        )
        with self.assertRaises(MODULE.CalendarError):
            MODULE.query_apple_calendar_range(
                start=start,
                end=start + timedelta(days=46),
                runner=self.eventkit_runner("[]"),
                helper_executable=ROOT / "scripts/apple_calendar_eventkit.swift",
            )

    def test_missing_eventkit_helper_fails_without_jxa_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing-helper"
            with self.assertRaises(MODULE.CalendarError) as raised:
                MODULE.query_apple_calendar(helper_executable=missing)
        self.assertIn("EventKit helper is unavailable", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
