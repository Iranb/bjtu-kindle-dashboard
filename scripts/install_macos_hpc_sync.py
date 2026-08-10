#!/usr/bin/env python3
"""Install or inspect the macOS launchd job for HPC-to-Kindle rendering."""

from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

from publish_kindle_live import PublishError, validate_branch, validate_remote
from publish_kindle_ssh import validate_remote_path, validate_target
from sync_hpc_widget import DEFAULT_SNAPSHOT


ROOT = Path(__file__).resolve().parents[1]
LABEL = "com.iranb.bjtu-kindle-sync"
DEFAULT_RUNTIME = (
    Path.home() / "Library" / "Application Support" / "BJTUKindleSync"
)
DEFAULT_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
RUNTIME_SCRIPTS = (
    "update_dashboard.py",
    "sync_hpc_widget.py",
    "publish_kindle_live.py",
    "publish_kindle_ssh.py",
    "run_hpc_kindle_sync.py",
)


class InstallError(RuntimeError):
    """Raised when the launchd installation cannot be completed safely."""


def build_plist(
    *,
    home: Path,
    python: Path,
    app_dir: Path,
    runtime_dir: Path,
    snapshot: Path,
    remote: str,
    ssh_target: str,
    ssh_path: str,
    branch: str,
    interval: int,
) -> dict[str, Any]:
    arguments = [
        "/usr/bin/env",
        "-i",
        f"HOME={home}",
        "PATH=/usr/bin:/bin:/usr/sbin:/sbin",
        "LANG=en_US.UTF-8",
        "PYTHONUNBUFFERED=1",
        str(python),
        str(app_dir / "run_hpc_kindle_sync.py"),
        "--snapshot",
        str(snapshot),
        "--runtime-dir",
        str(runtime_dir),
        "--branch",
        branch,
    ]
    if remote:
        arguments.extend(["--remote", remote])
    elif ssh_target:
        arguments.extend(["--ssh-target", ssh_target, "--ssh-path", ssh_path])
    return {
        "Label": LABEL,
        "ProgramArguments": arguments,
        "WorkingDirectory": str(app_dir),
        "RunAtLoad": True,
        "StartInterval": interval,
        "WatchPaths": [str(snapshot)],
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "Nice": 10,
        "ThrottleInterval": 30,
        "StandardOutPath": str(runtime_dir / "logs" / "stdout.log"),
        "StandardErrorPath": str(runtime_dir / "logs" / "stderr.log"),
    }


def write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        temporary.write_bytes(content)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def launchctl(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["launchctl", *arguments],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip().splitlines()
        message = detail[-1] if detail else f"exit {result.returncode}"
        raise InstallError(f"launchctl {arguments[0]} failed: {message}")
    return result


def plist_for_args(args: argparse.Namespace, python: Path, app_dir: Path) -> dict[str, Any]:
    return build_plist(
        home=Path.home(),
        python=python,
        app_dir=app_dir,
        runtime_dir=args.runtime_dir,
        snapshot=args.snapshot,
        remote=args.remote,
        ssh_target=args.ssh_target,
        ssh_path=args.ssh_path,
        branch=args.branch,
        interval=args.interval,
    )


def install(args: argparse.Namespace) -> None:
    runtime = args.runtime_dir
    app_dir = runtime / "app"
    venv_dir = runtime / "venv"
    logs_dir = runtime / "logs"
    app_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    for name in RUNTIME_SCRIPTS:
        source = ROOT / "scripts" / name
        if not source.is_file():
            raise InstallError(f"missing runtime source: {source}")
        shutil.copy2(source, app_dir / name)
    requirements = ROOT / "requirements.txt"
    shutil.copy2(requirements, app_dir / "requirements.txt")

    venv_python = venv_dir / "bin" / "python3"
    if not venv_python.is_file():
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    subprocess.run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--quiet",
            "-r",
            str(app_dir / "requirements.txt"),
        ],
        check=True,
    )

    plist = plist_for_args(args, venv_python, app_dir)
    write_atomic(args.plist, plistlib.dumps(plist, fmt=plistlib.FMT_XML, sort_keys=True))
    domain = f"gui/{os.getuid()}"
    launchctl("bootout", domain, str(args.plist), check=False)
    launchctl("bootstrap", domain, str(args.plist))
    launchctl("kickstart", "-k", f"{domain}/{LABEL}")


def uninstall(args: argparse.Namespace) -> None:
    domain = f"gui/{os.getuid()}"
    launchctl("bootout", domain, str(args.plist), check=False)
    args.plist.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--print-plist", action="store_true")
    action.add_argument("--install", action="store_true")
    action.add_argument("--uninstall", action="store_true")
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--plist", type=Path, default=DEFAULT_PLIST)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument(
        "--remote",
        default="",
        help="credential-free Git remote; omit for local rendering only",
    )
    destination.add_argument(
        "--ssh-target",
        default="",
        help="credential-free SSH Host alias for a private HTTPS edge",
    )
    parser.add_argument(
        "--ssh-path",
        default=".local/share/bjtu-kindle-edge/www/panel-base.png",
    )
    parser.add_argument("--branch", default="kindle-live")
    parser.add_argument("--interval", type=int, default=300)
    return parser


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.runtime_dir = args.runtime_dir.expanduser().resolve()
    args.plist = args.plist.expanduser().resolve()
    args.snapshot = args.snapshot.expanduser().resolve()
    if args.interval < 60 or args.interval > 86400:
        parser.error("--interval must be 60..86400")
    try:
        validate_branch(args.branch)
        if args.remote:
            validate_remote(args.remote)
        if args.ssh_target:
            validate_target(args.ssh_target)
            validate_remote_path(args.ssh_path)
    except PublishError as exc:
        parser.error(str(exc))
    return args


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.print_plist:
            app_dir = args.runtime_dir / "app"
            python = args.runtime_dir / "venv" / "bin" / "python3"
            sys.stdout.buffer.write(
                plistlib.dumps(
                    plist_for_args(args, python, app_dir),
                    fmt=plistlib.FMT_XML,
                    sort_keys=True,
                )
            )
        elif args.install:
            install(args)
            print(f"installed={LABEL} plist={args.plist}")
        else:
            uninstall(args)
            print(f"uninstalled={LABEL} runtime_preserved={args.runtime_dir}")
    except (InstallError, OSError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
