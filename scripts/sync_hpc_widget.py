#!/usr/bin/env python3
"""Render an anonymized Kindle panel from the local BJTU HPC Widget snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from PIL import Image


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from update_dashboard import HEIGHT, WIDTH, Renderer, validate  # noqa: E402


DEFAULT_SNAPSHOT = (
    Path.home()
    / "Library"
    / "Containers"
    / "com.iranb.bjtu-hpc-native-widget.widget"
    / "Data"
    / "Library"
    / "Application Support"
    / "BJTUHPCNativeWidget"
    / "snapshot.json"
)
DEFAULT_ACCOUNT_LABELS = tuple(f"ACCOUNT {letter}" for letter in "ABCDEF")


class SyncError(RuntimeError):
    """Raised when the source snapshot cannot produce a safe panel."""


def as_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SyncError(f"cannot read JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SyncError(f"JSON root must be an object: {path}")
    return value


def parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def source_is_stale(snapshot: dict[str, Any], max_age_seconds: int, now: datetime) -> bool:
    written_at = parse_timestamp(snapshot.get("written_at"))
    age = float("inf") if written_at is None else max(0.0, (now - written_at).total_seconds())
    return bool(
        snapshot.get("stale_payload")
        or as_int(snapshot.get("returncode")) != 0
        or snapshot.get("error")
        or age > max_age_seconds
    )


def node_status(value: Any) -> str:
    state = str(value or "UNKNOWN").strip().upper()
    if any(token in state for token in ("DOWN", "DRAIN", "FAIL", "UNKNOWN")):
        return "OFFLINE"
    if "IDLE" in state:
        return "READY"
    if "MIXED" in state:
        return "MIXED"
    if "ALLOC" in state or "FULL" in state:
        return "FULL"
    return state[:12] or "UNKNOWN"


def account_status(
    account: dict[str, Any], guardian_row: dict[str, Any] | None
) -> str:
    guardian_row = guardian_row or {}
    if (
        account.get("error")
        or account.get("has_token") is not True
        or guardian_row.get("attention_required")
        or guardian_row.get("needs_visible_login")
        or guardian_row.get("status") not in (None, "valid")
    ):
        return "SIGN-IN"
    if as_int((account.get("summary") or {}).get("pending")) > 0:
        return "WAITING"
    return "HEALTHY"


def dashboard_from_snapshot(
    snapshot: dict[str, Any],
    *,
    account_labels: tuple[str, ...] = DEFAULT_ACCOUNT_LABELS,
    max_age_seconds: int = 900,
    now: datetime | None = None,
) -> dict[str, Any]:
    if len(account_labels) != 6:
        raise SyncError("exactly six account labels are required")
    payload = snapshot.get("payload")
    if not isinstance(payload, dict):
        raise SyncError("snapshot.payload must be an object")
    resources = payload.get("cluster_resources")
    if not isinstance(resources, dict):
        raise SyncError("snapshot payload has no cluster_resources object")

    source_nodes = [node for node in (resources.get("nodes") or []) if isinstance(node, dict)]
    source_nodes.sort(key=lambda row: str(row.get("name") or ""))
    if len(source_nodes) != 4:
        raise SyncError(f"expected exactly four visible GPU nodes, got {len(source_nodes)}")

    guardian_accounts = as_dict(as_dict(snapshot.get("guardian")).get("accounts"))
    source_accounts = [
        account for account in (payload.get("accounts") or []) if isinstance(account, dict)
    ]
    source_accounts.sort(key=lambda row: str(row.get("name") or ""))
    if len(source_accounts) > 6:
        raise SyncError(f"expected at most six accounts, got {len(source_accounts)}")

    accounts: list[dict[str, Any]] = []
    account_problem = False
    for index, label in enumerate(account_labels):
        if index >= len(source_accounts):
            accounts.append(
                {"name": label, "status": "SIGN-IN", "running": 0, "queued": 0}
            )
            account_problem = True
            continue
        source = source_accounts[index]
        source_name = str(source.get("name") or "")
        guardian_row = guardian_accounts.get(source_name)
        status = account_status(
            source, guardian_row if isinstance(guardian_row, dict) else None
        )
        summary = as_dict(source.get("summary"))
        accounts.append(
            {
                "name": label,
                "status": status,
                "running": as_int(summary.get("running")),
                "queued": as_int(summary.get("pending")),
            }
        )
        account_problem = account_problem or status == "SIGN-IN"

    nodes = []
    node_problem = False
    for index, source in enumerate(source_nodes, start=1):
        total = max(1, as_int(source.get("gpu_total")))
        free = min(total, as_int(source.get("gpu_free")))
        status = node_status(source.get("state"))
        node_problem = node_problem or status == "OFFLINE"
        nodes.append(
            {
                # Hostnames are local inventory data. Keep only a stable ordinal.
                "name": f"GPU{index:02d}",
                "state": status,
                "free": free,
                "total": total,
            }
        )

    summary = as_dict(resources.get("summary"))
    stale = source_is_stale(
        snapshot,
        max_age_seconds,
        (now or datetime.now(timezone.utc)).astimezone(timezone.utc),
    )
    jobs_running = sum(account["running"] for account in accounts)
    jobs_queued = sum(account["queued"] for account in accounts)
    healthy = not (
        stale
        or resources.get("error")
        or account_problem
        or node_problem
    )
    dashboard = {
        "cluster": {
            "name": "BJTU COMPUTE",
            "subtitle": "HPC SNAPSHOT · STALE" if stale else "HPC SNAPSHOT · LIVE",
        },
        "header": {"time": "00:00", "date": "MON . JAN 1", "battery": 100},
        "capacity": {
            "gpus_free": as_int(summary.get("gpu_free")),
            "gpus_total": max(1, as_int(summary.get("gpu_total"))),
            "cpu_cores_free": as_int(summary.get("cpu_free")),
            "jobs_running": jobs_running,
            "jobs_queued": jobs_queued,
            "all_systems_online": healthy,
        },
        "nodes": nodes,
        "accounts": accounts,
    }
    return validate(dashboard)


def canonical_digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def render_atomic(path: Path, dashboard: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        image = Renderer(dashboard, "blank").render()
        image.save(temporary, format="PNG", optimize=True)
        with Image.open(temporary) as verified:
            if verified.size != (WIDTH, HEIGHT) or verified.mode != "L":
                raise SyncError(
                    f"rendered PNG contract mismatch: size={verified.size} mode={verified.mode}"
                )
            verified.verify()
        digest = file_digest(temporary)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
        return digest
    finally:
        temporary.unlink(missing_ok=True)


def sync_once(args: argparse.Namespace) -> dict[str, Any]:
    snapshot = load_json(args.snapshot)
    dashboard = dashboard_from_snapshot(
        snapshot,
        account_labels=tuple(args.account_label),
        max_age_seconds=args.max_source_age,
    )
    semantic_sha256 = canonical_digest(dashboard)
    previous_state: dict[str, Any] = {}
    if args.state_file.is_file():
        try:
            previous_state = load_json(args.state_file)
        except SyncError:
            previous_state = {}

    should_render = bool(
        args.force
        or not args.image_output.is_file()
        or previous_state.get("semantic_sha256") != semantic_sha256
    )
    atomic_write_json(args.data_output, dashboard)
    if should_render:
        image_sha256 = render_atomic(args.image_output, dashboard)
    else:
        image_sha256 = file_digest(args.image_output)

    state = {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source_written_at": snapshot.get("written_at"),
        "source_checked_at": (snapshot.get("payload") or {}).get("checked_at_local"),
        "semantic_sha256": semantic_sha256,
        "image_sha256": image_sha256,
        "stale": "STALE" in dashboard["cluster"]["subtitle"],
    }
    atomic_write_json(args.state_file, state)
    return {
        "changed": should_render,
        "image": str(args.image_output.resolve()),
        "image_sha256": image_sha256,
        "size": [WIDTH, HEIGHT],
        "mode": "L",
        "stale": state["stale"],
        "source_checked_at": state["source_checked_at"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--image-output", type=Path, required=True)
    parser.add_argument("--data-output", type=Path, required=True)
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--max-source-age", type=int, default=900)
    parser.add_argument(
        "--account-label",
        action="append",
        default=[],
        help="anonymous display label; provide exactly six or omit for ACCOUNT A-F",
    )
    parser.add_argument("--force", action="store_true")
    return parser


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_source_age < 60 or args.max_source_age > 86400:
        parser.error("--max-source-age must be 60..86400")
    if not args.account_label:
        args.account_label = list(DEFAULT_ACCOUNT_LABELS)
    if len(args.account_label) != 6:
        parser.error("provide exactly six --account-label values")
    return args


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        receipt = sync_once(args)
    except SyncError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
