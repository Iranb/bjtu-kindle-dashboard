#!/usr/bin/env python3
"""Serve validated portrait/right Kindle panels over HTTPS with ETag."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import re
import ssl
import stat
import struct
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable, NamedTuple, Optional
from urllib.parse import urlsplit


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
WIDTH = 1072
HEIGHT = 1448


class PanelError(RuntimeError):
    """Raised when the published image violates the device contract."""


class Panel(NamedTuple):
    data: bytes
    etag: str
    modified: float


def read_panel(path: Path, max_bytes: int) -> Panel:
    try:
        with path.open("rb") as handle:
            descriptor = handle.fileno()
            data = handle.read(max_bytes + 1)
            modified = os.fstat(descriptor).st_mtime
    except OSError as exc:
        raise PanelError(f"cannot read panel: {exc}") from exc
    if not data or len(data) > max_bytes:
        raise PanelError("panel size is invalid")
    if len(data) < 29 or data[:8] != PNG_SIGNATURE:
        raise PanelError("panel is not PNG")
    length = struct.unpack(">I", data[8:12])[0]
    if length != 13 or data[12:16] != b"IHDR":
        raise PanelError("panel has no canonical IHDR")
    width, height, depth, color, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", data[16:29]
    )
    if (width, height, depth, color, compression, filtering, interlace) != (
        WIDTH,
        HEIGHT,
        8,
        0,
        0,
        0,
        0,
    ):
        raise PanelError("panel PNG contract mismatch")
    digest = hashlib.sha256(data).hexdigest()
    return Panel(data=data, etag=f'"sha256-{digest}"', modified=modified)


def make_handler(
    panel_path: Path,
    max_bytes: int,
    right_panel_path: Optional[Path] = None,
    calendar_panel_path: Optional[Path] = None,
    calendar_right_panel_path: Optional[Path] = None,
    calendar_token: Optional[str] = None,
) -> type[BaseHTTPRequestHandler]:
    routes: dict[str, tuple[Path, bool]] = {"/panel-base.png": (panel_path, False)}
    if right_panel_path is not None:
        routes["/panel-base-right.png"] = (right_panel_path, False)
    if calendar_panel_path is not None:
        routes["/panel-calendar.png"] = (calendar_panel_path, True)
    if calendar_right_panel_path is not None:
        routes["/panel-calendar-right.png"] = (calendar_right_panel_path, True)

    class PanelHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "BJTUKindleEdge/1"
        sys_version = ""

        def log_message(self, _format: str, *_args: object) -> None:
            # Do not retain client addresses or request headers in service logs.
            return

        def do_HEAD(self) -> None:  # noqa: N802
            self._respond(head_only=True)

        def do_GET(self) -> None:  # noqa: N802
            self._respond(head_only=False)

        def _plain(self, status: int, body: bytes, head_only: bool) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if not head_only:
                self.wfile.write(body)

        def _respond(self, head_only: bool) -> None:
            route = urlsplit(self.path).path
            if route == "/healthz":
                self._plain(200, b"ok\n", head_only)
                return
            selected = routes.get(route)
            if selected is None:
                self._plain(404, b"not found\n", head_only)
                return
            panel_path_for_route, needs_calendar_auth = selected
            if needs_calendar_auth:
                expected = f"Bearer {calendar_token or ''}"
                supplied = self.headers.get("Authorization", "")
                if not calendar_token or not hmac.compare_digest(supplied, expected):
                    # Do not disclose whether a protected calendar route exists.
                    self._plain(404, b"not found\n", head_only)
                    return
            try:
                panel = read_panel(panel_path_for_route, max_bytes)
            except PanelError:
                self._plain(503, b"panel unavailable\n", head_only)
                return

            request_etags = {
                value.strip()
                for value in self.headers.get("If-None-Match", "").split(",")
            }
            if "*" in request_etags or panel.etag in request_etags:
                self.send_response(304)
                self.send_header("ETag", panel.etag)
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                return

            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(panel.data)))
            self.send_header("ETag", panel.etag)
            self.send_header("Last-Modified", formatdate(panel.modified, usegmt=True))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if not head_only:
                self.wfile.write(panel.data)

    return PanelHandler


def read_calendar_token(path: Path) -> str:
    try:
        metadata = path.stat()
        token = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise PanelError("cannot read calendar token") from exc
    if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise PanelError("calendar token file must be private")
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
        raise PanelError("calendar token is invalid")
    return token


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--right-panel", type=Path)
    parser.add_argument("--calendar-panel", type=Path)
    parser.add_argument("--calendar-right-panel", type=Path)
    parser.add_argument("--calendar-token-file", type=Path)
    parser.add_argument("--cert", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=41443)
    parser.add_argument("--max-image-bytes", type=int, default=2 * 1024 * 1024)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.port < 1024 or args.port > 65535:
        raise SystemExit("--port must be 1024..65535")
    if args.max_image_bytes < 1024 or args.max_image_bytes > 16 * 1024 * 1024:
        raise SystemExit("--max-image-bytes must be 1024..16777216")
    # Fail before binding rather than serving a broken or missing initial panel.
    read_panel(args.panel, args.max_image_bytes)
    if args.right_panel is not None:
        read_panel(args.right_panel, args.max_image_bytes)
    calendar_paths = (args.calendar_panel, args.calendar_right_panel)
    if any(path is not None for path in calendar_paths) and not all(
        path is not None for path in calendar_paths
    ):
        raise SystemExit("calendar portrait and right panels must be configured together")
    calendar_token = None
    if all(path is not None for path in calendar_paths):
        if args.calendar_token_file is None:
            raise SystemExit("--calendar-token-file is required for calendar panels")
        assert args.calendar_panel is not None
        assert args.calendar_right_panel is not None
        read_panel(args.calendar_panel, args.max_image_bytes)
        read_panel(args.calendar_right_panel, args.max_image_bytes)
        calendar_token = read_calendar_token(args.calendar_token_file)
    server = ThreadingHTTPServer(
        (args.bind, args.port),
        make_handler(
            args.panel,
            args.max_image_bytes,
            args.right_panel,
            args.calendar_panel,
            args.calendar_right_panel,
            calendar_token,
        ),
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.options |= getattr(ssl, "OP_NO_COMPRESSION", 0)
    context.load_cert_chain(certfile=args.cert, keyfile=args.key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
