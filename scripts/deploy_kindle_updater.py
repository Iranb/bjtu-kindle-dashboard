#!/usr/bin/env python3
"""Deploy and install the scheduled dashboard updater on a Kindle."""

from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / "kindle" / "bjtu-dashboard-updater"
REMOTE_PARENT = "/mnt/us/extensions"
REMOTE_DIR = f"{REMOTE_PARENT}/bjtu-dashboard-updater"


def require_command(name: str) -> None:
    if not shutil.which(name):
        raise RuntimeError(f"{name} is required")


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def deploy(host: str, install: bool) -> None:
    require_command("scp")
    require_command("ssh")
    if not PAYLOAD.is_dir():
        raise RuntimeError(f"missing updater payload: {PAYLOAD}")

    run(["scp", "-r", str(PAYLOAD), f"{host}:{REMOTE_PARENT}/"])

    remote = (
        f"find {shlex.quote(REMOTE_DIR)} -type f "
        "\\( -name '*.sh' -o -name '*.conf' -o -name '*.conf.example' \\) "
        "-exec sed -i 's/\\r$//' {} \\; && "
        f"chmod 755 {shlex.quote(REMOTE_DIR)}/install.sh "
        f"{shlex.quote(REMOTE_DIR)}/bin/*.sh"
    )
    if install:
        remote += f" && /bin/sh {shlex.quote(REMOTE_DIR)}/install.sh install"
    run(["ssh", host, remote])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="SSH host or alias for the Kindle")
    parser.add_argument(
        "--copy-only",
        action="store_true",
        help="copy the payload without installing or restarting the Upstart job",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        deploy(args.host, install=not args.copy_only)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"deployed={args.host}:{REMOTE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
