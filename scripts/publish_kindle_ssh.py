#!/usr/bin/env python3
"""Atomically publish a validated Kindle panel to an SSH edge host."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from publish_kindle_live import PublishError, validate_image


DEFAULT_REMOTE_PATH = ".local/share/bjtu-kindle-edge/www/panel-base.png"
DEFAULT_REMOTE_RIGHT_PATH = ".local/share/bjtu-kindle-edge/www/panel-base-right.png"
DEFAULT_REMOTE_CALENDAR_PATH = ".local/share/bjtu-kindle-edge/www/panel-calendar.png"
DEFAULT_REMOTE_CALENDAR_RIGHT_PATH = (
    ".local/share/bjtu-kindle-edge/www/panel-calendar-right.png"
)


def validate_target(target: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", target):
        raise PublishError("SSH target must be a credential-free Host alias")
    return target


def validate_remote_path(remote_path: str) -> str:
    if (
        not re.fullmatch(r"[A-Za-z0-9.][A-Za-z0-9._/-]{0,511}", remote_path)
        or remote_path.startswith("/")
        or any(part in ("", ".", "..") for part in remote_path.split("/"))
        or "//" in remote_path
        or remote_path.endswith("/")
    ):
        raise PublishError("remote path must be a safe path relative to SSH HOME")
    return remote_path


def ssh(target: str, command: str, *, stdin: Any = None) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "LogLevel=ERROR",
            target,
            command,
        ],
        stdin=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        lines = result.stderr.decode("utf-8", "replace").strip().splitlines()
        detail = lines[-1] if lines else f"exit {result.returncode}"
        raise PublishError(f"SSH publish failed: {detail}")
    return result


def publish_ssh(
    *,
    image: Path,
    target: str,
    remote_path: str = DEFAULT_REMOTE_PATH,
    max_bytes: int = 2 * 1024 * 1024,
) -> dict[str, Any]:
    target = validate_target(target)
    remote_path = validate_remote_path(remote_path)
    manifest = validate_image(image, max_bytes)
    destination = f"$HOME/{remote_path}"
    current = ssh(
        target,
        f"if [ -f \"{destination}\" ]; then sha256sum \"{destination}\" | awk '{{print $1}}'; fi",
    ).stdout.decode("ascii", "replace").strip()
    if current == manifest["sha256"]:
        return {
            "changed": False,
            "image_sha256": manifest["sha256"],
            "remote_path": remote_path,
        }
    if current and not re.fullmatch(r"[0-9a-f]{64}", current):
        raise PublishError("remote returned an invalid SHA-256 value")

    incoming = f"{destination}.incoming.{manifest['sha256'][:16]}"
    parent = destination.rsplit("/", 1)[0]
    command = (
        "set -eu; umask 077; "
        f"mkdir -p \"{parent}\"; incoming=\"{incoming}\"; "
        "trap 'rm -f \"$incoming\"' 0 1 2 15; "
        "cat > \"$incoming\"; "
        f"[ \"$(wc -c < \"$incoming\")\" = \"{manifest['bytes']}\" ]; "
        f"[ \"$(sha256sum \"$incoming\" | awk '{{print $1}}')\" = \"{manifest['sha256']}\" ]; "
        "chmod 644 \"$incoming\"; "
        f"mv -f \"$incoming\" \"{destination}\"; trap - 0 1 2 15"
    )
    with image.open("rb") as handle:
        ssh(target, command, stdin=handle)
    verified = ssh(
        target, f"sha256sum \"{destination}\" | awk '{{print $1}}'"
    ).stdout.decode("ascii", "replace").strip()
    if verified != manifest["sha256"]:
        raise PublishError("remote SHA-256 differs after atomic replacement")
    return {
        "changed": True,
        "image_sha256": manifest["sha256"],
        "remote_path": remote_path,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--remote-path", default=DEFAULT_REMOTE_PATH)
    parser.add_argument("--max-image-bytes", type=int, default=2 * 1024 * 1024)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = publish_ssh(
            image=args.image,
            target=args.target,
            remote_path=args.remote_path,
            max_bytes=args.max_image_bytes,
        )
    except PublishError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
