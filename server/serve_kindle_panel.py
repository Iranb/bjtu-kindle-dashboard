#!/usr/bin/env python3
"""Serve one validated Kindle panel over authenticated HTTPS with ETag."""

from __future__ import annotations

import argparse
import hashlib
import os
import ssl
import struct
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable, NamedTuple
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


def make_handler(panel_path: Path, max_bytes: int) -> type[BaseHTTPRequestHandler]:
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
            if route != "/panel-base.png":
                self._plain(404, b"not found\n", head_only)
                return
            try:
                panel = read_panel(panel_path, max_bytes)
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, required=True)
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
    server = ThreadingHTTPServer(
        (args.bind, args.port), make_handler(args.panel, args.max_image_bytes)
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
