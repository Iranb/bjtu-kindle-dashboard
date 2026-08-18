#!/usr/bin/env python3
"""Read a minimal, bounded agenda from the current macOS Apple Calendar.

Only event title, start/end timestamps, and the all-day flag leave Calendar.
The caller is responsible for keeping the returned data in memory and publishing
only the final rendered image.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


JXA_QUERY = r"""
function run(argv) {
  const calendar = Application("Calendar");
  const start = new Date(argv[0]);
  const end = new Date(argv[1]);
  const rows = [];
  for (const source of calendar.calendars()) {
    let events = [];
    try {
      events = source.events.whose({_and: [
        {startDate: {_lessThan: end}},
        {endDate: {_greaterThan: start}}
      ]})();
    } catch (error) {
      continue;
    }
    for (const event of events) {
      try {
        rows.push({
          title: String(event.summary() || ""),
          start: event.startDate().toISOString(),
          end: event.endDate().toISOString(),
          all_day: Boolean(event.alldayEvent())
        });
      } catch (error) {}
    }
  }
  return JSON.stringify(rows);
}
"""


class CalendarError(RuntimeError):
    """Raised when Calendar cannot produce a safe agenda."""


SCRIPT_DIR = Path(__file__).resolve().parent
HELPER_EXECUTABLE = (
    SCRIPT_DIR
    / "AppleCalendarAgendaReader.app"
    / "Contents"
    / "MacOS"
    / "applet"
)


def _parse_timestamp(value: Any) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CalendarError("Apple Calendar returned an invalid timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clean_title(value: Any, limit: int = 80) -> str:
    title = re.sub(r"\s+", " ", str(value or "")).strip()
    title = "".join(character for character in title if character.isprintable())
    if not title:
        title = "UNTITLED EVENT"
    if len(title) > limit:
        title = title[: limit - 1].rstrip() + "…"
    return title


def normalize_agenda(
    rows: Any,
    *,
    start: datetime,
    end: datetime,
    max_events: int,
) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        raise CalendarError("Apple Calendar response must be a list")
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, bool]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        event_start = _parse_timestamp(row.get("start"))
        event_end = _parse_timestamp(row.get("end"))
        if event_end <= start or event_start >= end or event_end <= event_start:
            continue
        all_day = bool(row.get("all_day"))
        title = _clean_title(row.get("title"))
        item = {
            "title": title,
            "start": event_start.isoformat().replace("+00:00", "Z"),
            "end": event_end.isoformat().replace("+00:00", "Z"),
            "all_day": all_day,
        }
        identity = (item["title"], item["start"], item["end"], all_day)
        if identity not in seen:
            seen.add(identity)
            normalized.append(item)
    normalized.sort(key=lambda item: (item["start"], not item["all_day"], item["title"]))
    return normalized[:max_events]


def query_apple_calendar(
    *,
    now: datetime | None = None,
    hours: int = 24,
    max_events: int = 5,
    timeout: int = 20,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[dict[str, Any]]:
    if hours < 1 or hours > 168:
        raise CalendarError("calendar window must be 1..168 hours")
    if max_events < 1 or max_events > 12:
        raise CalendarError("calendar event limit must be 1..12")
    start = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    end = start + timedelta(hours=hours)
    return query_apple_calendar_range(
        start=start,
        end=end,
        max_events=max_events,
        timeout=timeout,
        runner=runner,
    )


def query_apple_calendar_range(
    *,
    start: datetime,
    end: datetime,
    max_events: int = 84,
    timeout: int = 20,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[dict[str, Any]]:
    """Read an explicit, bounded range suitable for a six-week month grid."""

    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)
    if end <= start or end - start > timedelta(days=45):
        raise CalendarError("calendar range must be positive and at most 45 days")
    if max_events < 1 or max_events > 84:
        raise CalendarError("calendar event limit must be 1..84")
    output_path: Path | None = None
    try:
        if HELPER_EXECUTABLE.is_file():
            temporary_dir = SCRIPT_DIR.parent / "tmp"
            temporary_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(temporary_dir, 0o700)
            descriptor, output_name = tempfile.mkstemp(
                prefix=".calendar-query.", dir=temporary_dir
            )
            os.close(descriptor)
            output_path = Path(output_name)
            os.chmod(output_path, 0o600)
            environment = os.environ.copy()
            environment.update(
                {
                    "BJTU_CALENDAR_START": start.isoformat(),
                    "BJTU_CALENDAR_END": end.isoformat(),
                    "BJTU_CALENDAR_OUTPUT": str(output_path),
                }
            )
            result = runner(
                [str(HELPER_EXECUTABLE)],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                env=environment,
            )
            raw_response = output_path.read_text(encoding="utf-8")
        else:
            result = runner(
                [
                    "/usr/bin/osascript",
                    "-l",
                    "JavaScript",
                    "-e",
                    JXA_QUERY,
                    start.isoformat(),
                    end.isoformat(),
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
            raw_response = result.stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CalendarError("Apple Calendar query was unavailable") from exc
    finally:
        if output_path is not None:
            output_path.unlink(missing_ok=True)
    if result.returncode != 0:
        # Calendar titles or application details must never enter service logs.
        raise CalendarError("Apple Calendar permission or query failed")
    try:
        rows = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise CalendarError("Apple Calendar returned invalid JSON") from exc
    return normalize_agenda(rows, start=start, end=end, max_events=max_events)


def main(argv: Iterable[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--max-events", type=int, default=5)
    args = parser.parse_args(argv)
    try:
        agenda = query_apple_calendar(hours=args.hours, max_events=args.max_events)
    except CalendarError as exc:
        print(f"error: {exc}")
        return 1
    # The command-line probe is deliberately content-free.
    print(json.dumps({"result": "ok", "event_count": len(agenda)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
