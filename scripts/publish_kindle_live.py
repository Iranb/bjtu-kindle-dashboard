#!/usr/bin/env python3
"""Publish one validated Kindle PNG to a single-commit Git branch."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

from PIL import Image


WIDTH = 1072
HEIGHT = 1448
IMAGE_PATH = Path("assets/panel-base.png")
MANIFEST_PATH = Path("assets/manifest.json")
MARKER = ".bjtu-kindle-live-publisher"
ALLOWED_REMOTE_FILES = {IMAGE_PATH.as_posix(), MANIFEST_PATH.as_posix()}


class PublishError(RuntimeError):
    """Raised when publishing would be unsafe or incomplete."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_image(path: Path, max_bytes: int) -> dict[str, Any]:
    if not path.is_file():
        raise PublishError(f"image does not exist: {path}")
    size = path.stat().st_size
    if size <= 0 or size > max_bytes:
        raise PublishError(f"image size is outside 1..{max_bytes} bytes: {size}")
    try:
        with Image.open(path) as image:
            if image.format != "PNG":
                raise PublishError(f"image format must be PNG, got {image.format}")
            if image.size != (WIDTH, HEIGHT) or image.mode != "L":
                raise PublishError(
                    f"image contract mismatch: size={image.size} mode={image.mode}"
                )
            image.verify()
    except OSError as exc:
        raise PublishError(f"cannot verify PNG: {exc}") from exc
    return {
        "version": 1,
        "path": IMAGE_PATH.as_posix(),
        "sha256": sha256_file(path),
        "bytes": size,
        "width": WIDTH,
        "height": HEIGHT,
        "mode": "L",
    }


def validate_branch(branch: str) -> str:
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", branch)
        or ".." in branch
        or "//" in branch
        or branch.endswith(("/", ".", ".lock"))
    ):
        raise PublishError(f"invalid branch name: {branch!r}")
    return branch


def validate_remote(remote: str) -> str:
    if not remote or any(character in remote for character in ("\n", "\r", "\0")):
        raise PublishError("remote must be a non-empty single-line value")
    if remote.startswith(("http://", "https://")):
        parsed = urlsplit(remote)
        if parsed.username is not None or parsed.password is not None:
            raise PublishError("remote URL must not embed credentials")
    return remote


def git(
    worktree: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *arguments],
        cwd=worktree,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip().splitlines()
        message = detail[-1] if detail else f"exit {result.returncode}"
        raise PublishError(f"git {arguments[0]} failed: {message}")
    return result


def prepare_worktree(worktree: Path, remote: str) -> None:
    marker = worktree / MARKER
    if worktree.exists():
        if not worktree.is_dir() or not marker.is_file():
            raise PublishError(
                f"refusing to reuse unmarked publisher worktree: {worktree}"
            )
    else:
        worktree.mkdir(parents=True)
        marker.write_text("managed by publish_kindle_live.py\n", encoding="utf-8")

    if not (worktree / ".git").is_dir():
        unexpected = [path.name for path in worktree.iterdir() if path.name != MARKER]
        if unexpected:
            raise PublishError(f"publisher worktree is not empty: {worktree}")
        git(worktree, "init", "--quiet")
        git(worktree, "remote", "add", "origin", remote)
        git(worktree, "config", "user.name", "BJTU Kindle Sync")
        git(worktree, "config", "user.email", "kindle-sync@localhost")
        return

    configured = git(worktree, "remote", "get-url", "origin", check=False)
    if configured.returncode != 0:
        git(worktree, "remote", "add", "origin", remote)
    elif configured.stdout.strip() != remote:
        raise PublishError("publisher worktree remote does not match requested remote")


def remote_head(worktree: Path, branch: str) -> str | None:
    result = git(
        worktree,
        "ls-remote",
        "--heads",
        "origin",
        f"refs/heads/{branch}",
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()
        message = detail[-1] if detail else f"exit {result.returncode}"
        raise PublishError(f"cannot query remote branch: {message}")
    fields = result.stdout.strip().split()
    return fields[0] if fields else None


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp.{os.getpid()}")
    try:
        shutil.copyfile(source, temporary)
        os.chmod(temporary, 0o644)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(destination: Path, value: dict[str, Any]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp.{os.getpid()}")
    try:
        temporary.write_text(
            json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        os.chmod(temporary, 0o644)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def publish(
    *,
    image: Path,
    worktree: Path,
    remote: str,
    branch: str = "kindle-live",
    max_bytes: int = 2 * 1024 * 1024,
) -> dict[str, Any]:
    if not shutil.which("git"):
        raise PublishError("git is required")
    branch = validate_branch(branch)
    remote = validate_remote(remote)
    manifest = validate_image(image, max_bytes)
    prepare_worktree(worktree, remote)

    old_head = remote_head(worktree, branch)
    destination = worktree / IMAGE_PATH
    manifest_path = worktree / MANIFEST_PATH
    if old_head:
        git(worktree, "fetch", "--quiet", "--no-tags", "origin", f"refs/heads/{branch}")
        count = git(worktree, "rev-list", "--count", "FETCH_HEAD").stdout.strip()
        if count != "1":
            raise PublishError(
                f"refusing to rewrite {branch}: expected one commit, found {count}"
            )
        names = {
            line
            for line in git(worktree, "ls-tree", "-r", "--name-only", "FETCH_HEAD")
            .stdout.strip()
            .splitlines()
            if line
        }
        if names != ALLOWED_REMOTE_FILES:
            raise PublishError(
                f"refusing to rewrite {branch}: unexpected remote files"
            )
        git(worktree, "checkout", "--quiet", "-B", branch, "FETCH_HEAD")
        if destination.is_file() and sha256_file(destination) == manifest["sha256"]:
            return {
                "changed": False,
                "branch": branch,
                "image_sha256": manifest["sha256"],
                "remote_head": old_head,
            }
    else:
        # Use a disposable local name so a failed first push remains retryable.
        # Reset the orphan index because Git otherwise carries tracked files from
        # the previously checked-out commit into the new root commit.
        staging_branch = f"bjtu-publish-staging-{uuid.uuid4().hex[:12]}"
        git(worktree, "checkout", "--quiet", "--orphan", staging_branch)
        git(worktree, "rm", "-r", "--cached", "--ignore-unmatch", ".")

    atomic_copy(image, destination)
    atomic_json(manifest_path, manifest)
    git(worktree, "add", "--", IMAGE_PATH.as_posix(), MANIFEST_PATH.as_posix())
    if old_head:
        git(worktree, "commit", "--quiet", "--amend", "--no-edit")
        lease = f"--force-with-lease=refs/heads/{branch}:{old_head}"
        git(worktree, "push", "--quiet", lease, "origin", f"HEAD:refs/heads/{branch}")
    else:
        git(worktree, "commit", "--quiet", "-m", "Publish Kindle live panel")
        git(worktree, "push", "--quiet", "origin", f"HEAD:refs/heads/{branch}")

    new_head = remote_head(worktree, branch)
    if not new_head:
        raise PublishError("remote branch is missing after push")
    return {
        "changed": True,
        "branch": branch,
        "image_sha256": manifest["sha256"],
        "remote_head": new_head,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--remote", required=True)
    parser.add_argument("--branch", default="kindle-live")
    parser.add_argument("--max-image-bytes", type=int, default=2 * 1024 * 1024)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_image_bytes < 1024 or args.max_image_bytes > 16 * 1024 * 1024:
        print("error: --max-image-bytes must be 1024..16777216", file=sys.stderr)
        return 2
    try:
        receipt = publish(
            image=args.image,
            worktree=args.worktree,
            remote=args.remote,
            branch=args.branch,
            max_bytes=args.max_image_bytes,
        )
    except PublishError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
