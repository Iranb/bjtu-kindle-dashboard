#!/usr/bin/env python3
"""Build, deploy, and privately configure the standalone Kindle calendar."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / "kindle" / "kindle-calendar"
REMOTE_PARENT = "/mnt/us/extensions"
REMOTE_DIR = f"{REMOTE_PARENT}/kindle-calendar"


def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, text=True, **kwargs)


def require_commands() -> None:
    for name in ("go", "scp", "ssh"):
        if shutil.which(name) is None:
            raise RuntimeError(f"{name} is required")


def device_arch(host: str) -> tuple[str, str | None]:
    result = run(["ssh", host, "uname -m"], capture_output=True)
    machine = result.stdout.strip()
    if machine in {"armv7l", "armv6l", "arm"}:
        return "arm", "7"
    if machine in {"aarch64", "arm64"}:
        return "arm64", None
    raise RuntimeError(f"unsupported Kindle architecture: {machine or 'unknown'}")


def read_feed(path: Path) -> str:
    raw = path.read_text(encoding="utf-8").strip()
    if "\n" in raw or "\r" in raw:
        raise RuntimeError("feed file must contain exactly one URL")
    normalized = "https://" + raw[len("webcal://") :] if raw.startswith("webcal://") else raw
    parsed = urlparse(normalized)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
        raise RuntimeError("feed must be a credential-free HTTPS or webcal URL")
    return raw


def build_payload(goarch: str, goarm: str | None, destination: Path) -> Path:
    target = destination / "kindle-calendar"
    shutil.copytree(PAYLOAD, target)
    env = os.environ.copy()
    env.update({"GOOS": "linux", "GOARCH": goarch, "CGO_ENABLED": "0"})
    if goarm is not None:
        env["GOARM"] = goarm
    run(
        [
            "go",
            "build",
            "-trimpath",
            "-ldflags=-s -w",
            "-o",
            str(target / "bin" / "kindle-calendar"),
            "./cmd/kindle-calendar",
        ],
        cwd=ROOT,
        env=env,
    )
    return target


def configure_private_feed(host: str, feed: str) -> None:
    # The URL travels only over SSH stdin. It is never placed in argv, the USB
    # partition, the repository, or updater logs.
    command = (
        "umask 077; mkdir -p /var/local/kindle-calendar; "
        "IFS= read -r FEED; case \"$FEED\" in https://*|webcal://*) ;; *) exit 2;; esac; "
        "printf '%s\\n' \"$FEED\" > /var/local/kindle-calendar/feed.url; "
        "chmod 600 /var/local/kindle-calendar/feed.url"
    )
    run(["ssh", host, command], input=feed + "\n")


def deploy(host: str, feed_file: Path | None, copy_only: bool) -> None:
    require_commands()
    goarch, goarm = device_arch(host)
    with tempfile.TemporaryDirectory(prefix="kindle-calendar-deploy-") as tmp:
        payload = build_payload(goarch, goarm, Path(tmp))
        run(["scp", "-O", "-r", str(payload), f"{host}:{REMOTE_PARENT}/"])
    remote_prepare = (
        f"find {REMOTE_DIR} -type f -name '*.sh' -exec sed -i 's/\\r$//' {{}} \\; && "
        f"chmod 755 {REMOTE_DIR}/install.sh {REMOTE_DIR}/bin/*.sh {REMOTE_DIR}/bin/kindle-calendar"
    )
    run(["ssh", host, remote_prepare])
    if copy_only:
        return
    run(["ssh", host, f"/bin/sh {REMOTE_DIR}/install.sh install"])
    if feed_file is not None:
        configure_private_feed(host, read_feed(feed_file))
        run(["ssh", host, f"/bin/sh {REMOTE_DIR}/bin/control.sh refresh"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="SSH host or alias for the jailbroken Kindle")
    parser.add_argument(
        "--feed-url-file",
        type=Path,
        help="optional local 0600 private ICS URL file for compatibility mode",
    )
    parser.add_argument("--copy-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.feed_url_file is not None and args.feed_url_file.stat().st_mode & 0o077:
            raise RuntimeError("local feed URL file permissions must be 0600")
        deploy(args.host, args.feed_url_file, args.copy_only)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("deployment complete; the Kindle now renders the calendar locally")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
