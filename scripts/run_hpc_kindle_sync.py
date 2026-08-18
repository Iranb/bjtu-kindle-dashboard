#!/usr/bin/env python3
"""Render the local HPC snapshot and optionally publish it for Kindle pickup."""

from __future__ import annotations

import argparse
import fcntl
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

from apple_calendar_agenda import CalendarError, query_apple_calendar_range
from publish_kindle_live import PublishError, publish
from publish_kindle_ssh import (
    DEFAULT_REMOTE_CALENDAR_PATH,
    DEFAULT_REMOTE_CALENDAR_RIGHT_PATH,
    DEFAULT_REMOTE_PATH,
    DEFAULT_REMOTE_RIGHT_PATH,
    publish_ssh,
    validate_remote_path,
    validate_target,
)
from sync_hpc_widget import (
    DEFAULT_ACCOUNT_LABELS,
    DEFAULT_SNAPSHOT,
    SyncError,
    atomic_write_json,
    sync_once,
)


DEFAULT_RUNTIME = (
    Path.home() / "Library" / "Application Support" / "BJTUKindleSync"
)
CALENDAR_TIMEZONE = ZoneInfo("Asia/Shanghai")


def current_month_grid_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return the Sunday-to-Saturday six-week grid used by Apple month view."""

    local_now = (now or datetime.now(timezone.utc)).astimezone(CALENDAR_TIMEZONE)
    month_start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    days_since_sunday = (month_start.weekday() + 1) % 7
    grid_start = month_start - timedelta(days=days_since_sunday)
    return grid_start.astimezone(timezone.utc), (grid_start + timedelta(days=42)).astimezone(timezone.utc)


def load_optional_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def run_once(args: argparse.Namespace) -> dict[str, Any]:
    runtime = args.runtime_dir.expanduser().resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    lock_path = runtime / "run.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"result": "skipped", "reason": "already_running"}

        safe_data = runtime / "state" / "dashboard.json"
        agenda = None
        if args.publish_calendar:
            calendar_start, calendar_end = current_month_grid_window()
            agenda = query_apple_calendar_range(
                start=calendar_start,
                end=calendar_end,
                max_events=args.calendar_max_events,
            )
        orientations = ("portrait", "right") if args.publish_both else (args.orientation,)
        modes = ("dashboard", "calendar") if args.publish_calendar else ("dashboard",)
        render_receipts: dict[tuple[str, str], dict[str, Any]] = {}
        outputs: dict[tuple[str, str], Path] = {}
        filenames = {
            ("dashboard", "portrait"): "panel-base.png",
            ("dashboard", "right"): "panel-base-right.png",
            ("calendar", "portrait"): "panel-calendar.png",
            ("calendar", "right"): "panel-calendar-right.png",
        }
        for mode in modes:
            for orientation in orientations:
                filename = filenames[(mode, orientation)]
                if mode == "calendar":
                    render_state = runtime / "state" / f"render-calendar-{orientation}.json"
                elif args.publish_both:
                    render_state = runtime / "state" / f"render-{orientation}.json"
                else:
                    render_state = runtime / "state" / "render.json"
                output = runtime / "outbox" / filename
                outputs[(mode, orientation)] = output
                sync_args = argparse.Namespace(
                    snapshot=args.snapshot.expanduser(),
                    image_output=output,
                    data_output=safe_data,
                    state_file=render_state,
                    max_source_age=args.max_source_age,
                    account_label=args.account_label,
                    force=args.force_render,
                    orientation=orientation,
                    agenda=agenda if mode == "calendar" else None,
                )
                render_receipts[(mode, orientation)] = sync_once(sync_args)

        hashes_by_mode = {
            mode: {
                orientation: render_receipts[(mode, orientation)]["image_sha256"]
                for orientation in orientations
            }
            for mode in modes
        }
        hashes: Any = hashes_by_mode if args.publish_calendar else hashes_by_mode["dashboard"]
        any_rendered = any(row["changed"] for row in render_receipts.values())
        receipt: dict[str, Any] = {
            "result": "rendered" if any_rendered else "unchanged",
            "image_sha256": hashes if (args.publish_both or args.publish_calendar) else hashes[args.orientation],
            "stale": any(row["stale"] for row in render_receipts.values()),
            "orientations": list(orientations),
            "calendar": "enabled" if args.publish_calendar else "disabled",
            "calendar_event_count": len(agenda or []),
        }
        if not args.remote and not args.ssh_target:
            receipt["publish"] = "disabled"
            return receipt

        publish_state_path = runtime / "state" / "publish.json"
        publish_state = load_optional_json(publish_state_path)
        if args.ssh_target:
            destination_matches = bool(
                publish_state.get("kind") == "ssh"
                and publish_state.get("target") == args.ssh_target
                and publish_state.get("remote_path") == args.ssh_path
                and (
                    not args.publish_both
                    or publish_state.get("remote_right_path") == args.ssh_right_path
                )
                and (
                    not args.publish_calendar
                    or (
                        publish_state.get("remote_calendar_path") == args.ssh_calendar_path
                        and publish_state.get("remote_calendar_right_path")
                        == args.ssh_calendar_right_path
                    )
                )
            )
        else:
            destination_matches = bool(
                publish_state.get("kind") == "git"
                and publish_state.get("branch") == args.branch
                and publish_state.get("remote") == args.remote
            )
        expected_hash_state: Any = (
            hashes if (args.publish_both or args.publish_calendar) else hashes[args.orientation]
        )
        if publish_state.get("image_sha256") == expected_hash_state and destination_matches:
            receipt["publish"] = "unchanged"
            return receipt

        if args.ssh_target:
            portrait_orientation = "portrait" if args.publish_both else args.orientation
            publish_receipt = publish_ssh(
                image=outputs[("dashboard", portrait_orientation)],
                target=args.ssh_target,
                remote_path=args.ssh_path,
                max_bytes=args.max_image_bytes,
            )
            right_publish_receipt: Optional[dict[str, Any]] = None
            if args.publish_both:
                right_publish_receipt = publish_ssh(
                    image=outputs[("dashboard", "right")],
                    target=args.ssh_target,
                    remote_path=args.ssh_right_path,
                    max_bytes=args.max_image_bytes,
                )
            calendar_publish_receipts: list[dict[str, Any]] = []
            if args.publish_calendar:
                calendar_publish_receipts.append(
                    publish_ssh(
                        image=outputs[("calendar", "portrait")],
                        target=args.ssh_target,
                        remote_path=args.ssh_calendar_path,
                        max_bytes=args.max_image_bytes,
                    )
                )
                calendar_publish_receipts.append(
                    publish_ssh(
                        image=outputs[("calendar", "right")],
                        target=args.ssh_target,
                        remote_path=args.ssh_calendar_right_path,
                        max_bytes=args.max_image_bytes,
                    )
                )
            published_state = {
                "version": 1,
                "kind": "ssh",
                "target": args.ssh_target,
                "remote_path": args.ssh_path,
                "image_sha256": expected_hash_state,
            }
            if args.publish_both:
                published_state["remote_right_path"] = args.ssh_right_path
            if args.publish_calendar:
                published_state["remote_calendar_path"] = args.ssh_calendar_path
                published_state["remote_calendar_right_path"] = args.ssh_calendar_right_path
        else:
            publish_receipt = publish(
                image=outputs[("dashboard", args.orientation)],
                worktree=runtime / "publisher",
                remote=args.remote,
                branch=args.branch,
                max_bytes=args.max_image_bytes,
            )
            published_state = {
                "version": 1,
                "kind": "git",
                "remote": args.remote,
                "branch": args.branch,
                "image_sha256": expected_hash_state,
                "remote_head": publish_receipt["remote_head"],
            }
        # Persist success only after the remote push or remote equality check.
        atomic_write_json(publish_state_path, published_state)
        publish_changed = publish_receipt["changed"]
        if args.ssh_target and args.publish_both and right_publish_receipt is not None:
            publish_changed = publish_changed or right_publish_receipt["changed"]
        if args.ssh_target and args.publish_calendar:
            publish_changed = publish_changed or any(
                row["changed"] for row in calendar_publish_receipts
            )
        receipt["publish"] = "updated" if publish_changed else "unchanged"
        if "remote_head" in publish_receipt:
            receipt["remote_head"] = publish_receipt["remote_head"]
        return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME)
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument(
        "--remote",
        default="",
        help="credential-free Git remote; omit to render locally without publishing",
    )
    destination.add_argument(
        "--ssh-target",
        default="",
        help="credential-free SSH Host alias for a private HTTPS edge",
    )
    parser.add_argument("--ssh-path", default=DEFAULT_REMOTE_PATH)
    parser.add_argument("--ssh-right-path", default=DEFAULT_REMOTE_RIGHT_PATH)
    parser.add_argument("--ssh-calendar-path", default=DEFAULT_REMOTE_CALENDAR_PATH)
    parser.add_argument(
        "--ssh-calendar-right-path", default=DEFAULT_REMOTE_CALENDAR_RIGHT_PATH
    )
    parser.add_argument("--branch", default="kindle-live")
    parser.add_argument("--max-source-age", type=int, default=900)
    parser.add_argument("--max-image-bytes", type=int, default=2 * 1024 * 1024)
    parser.add_argument("--force-render", action="store_true")
    parser.add_argument(
        "--orientation",
        choices=("portrait", "right"),
        default="portrait",
    )
    parser.add_argument(
        "--publish-both",
        action="store_true",
        help="render and publish portrait plus right variants (SSH edge only)",
    )
    parser.add_argument(
        "--publish-calendar",
        action="store_true",
        help="read Apple Calendar locally and publish protected month-view variants",
    )
    parser.add_argument("--calendar-hours", type=int, default=1008)
    parser.add_argument("--calendar-max-events", type=int, default=84)
    parser.add_argument("--account-label", action="append", default=[])
    return parser


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_source_age < 60 or args.max_source_age > 86400:
        parser.error("--max-source-age must be 60..86400")
    if args.max_image_bytes < 1024 or args.max_image_bytes > 16 * 1024 * 1024:
        parser.error("--max-image-bytes must be 1024..16777216")
    if not args.account_label:
        args.account_label = list(DEFAULT_ACCOUNT_LABELS)
    if len(args.account_label) != 6:
        parser.error("provide exactly six --account-label values")
    try:
        if args.publish_both and args.remote:
            parser.error("--publish-both currently requires --ssh-target or local-only")
        if args.publish_calendar and (not args.ssh_target or not args.publish_both):
            parser.error("--publish-calendar requires --ssh-target and --publish-both")
        if args.calendar_hours != 1008:
            parser.error("--calendar-hours must be 1008 for the six-week month view")
        if args.calendar_max_events < 1 or args.calendar_max_events > 84:
            parser.error("--calendar-max-events must be 1..84")
        if args.ssh_target:
            validate_target(args.ssh_target)
            validate_remote_path(args.ssh_path)
            validate_remote_path(args.ssh_right_path)
            validate_remote_path(args.ssh_calendar_path)
            validate_remote_path(args.ssh_calendar_right_path)
            if args.publish_both and args.ssh_path == args.ssh_right_path:
                parser.error("--ssh-path and --ssh-right-path must differ")
            selected_paths = [args.ssh_path, args.ssh_right_path]
            if args.publish_calendar:
                selected_paths.extend(
                    [args.ssh_calendar_path, args.ssh_calendar_right_path]
                )
            if len(selected_paths) != len(set(selected_paths)):
                parser.error("all SSH panel paths must differ")
    except PublishError as exc:
        parser.error(str(exc))
    return args


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        receipt = run_once(args)
    except (CalendarError, SyncError, PublishError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
