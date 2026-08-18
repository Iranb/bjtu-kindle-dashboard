import importlib.util
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "serve_kindle_panel", ROOT / "server" / "serve_kindle_panel.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class EdgeServerTests(unittest.TestCase):
    def test_edge_runner_is_posix_shell(self) -> None:
        runner = ROOT / "server" / "run_edge_server.sh"
        self.assertTrue(runner.read_bytes().startswith(b"#!/bin/sh\n"))
        result = subprocess.run(
            ["/bin/sh", "-n", str(runner)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_panel_contract_and_etag_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            panel_path = Path(temporary) / "panel.png"
            right_panel_path = Path(temporary) / "panel-right.png"
            calendar_panel_path = Path(temporary) / "calendar.png"
            calendar_right_panel_path = Path(temporary) / "calendar-right.png"
            Image.new("L", (1072, 1448), 255).save(panel_path)
            Image.new("L", (1072, 1448), 128).save(right_panel_path)
            Image.new("L", (1072, 1448), 64).save(calendar_panel_path)
            Image.new("L", (1072, 1448), 32).save(calendar_right_panel_path)
            panel = MODULE.read_panel(panel_path, 2 * 1024 * 1024)
            self.assertTrue(panel.etag.startswith('"sha256-'))

            server = ThreadingHTTPServer(
                ("127.0.0.1", 0),
                MODULE.make_handler(
                    panel_path,
                    2 * 1024 * 1024,
                    right_panel_path,
                    calendar_panel_path,
                    calendar_right_panel_path,
                    "x" * 48,
                ),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = HTTPConnection("127.0.0.1", server.server_port)
                connection.request("GET", "/panel-base.png")
                response = connection.getresponse()
                body = response.read()
                etag = response.getheader("ETag")
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader("Content-Type"), "image/png")
                self.assertEqual(body, panel_path.read_bytes())
                self.assertEqual(etag, panel.etag)

                connection.request(
                    "GET", "/panel-base.png", headers={"If-None-Match": etag}
                )
                cached = connection.getresponse()
                self.assertEqual(cached.status, 304)
                self.assertEqual(cached.read(), b"")

                connection.request("GET", "/panel-base-right.png")
                right = connection.getresponse()
                self.assertEqual(right.status, 200)
                self.assertEqual(right.read(), right_panel_path.read_bytes())
                self.assertNotEqual(right.getheader("ETag"), etag)

                connection.request("GET", "/panel-calendar.png")
                protected = connection.getresponse()
                self.assertEqual(protected.status, 404)
                protected.read()

                connection.request(
                    "GET",
                    "/panel-calendar.png",
                    headers={"Authorization": f"Bearer {'x' * 48}"},
                )
                calendar = connection.getresponse()
                self.assertEqual(calendar.status, 200)
                self.assertEqual(calendar.read(), calendar_panel_path.read_bytes())

                connection.request("GET", "/healthz")
                health = connection.getresponse()
                self.assertEqual(health.status, 200)
                self.assertEqual(health.read(), b"ok\n")
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_rejects_non_grayscale_png(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            panel_path = Path(temporary) / "panel.png"
            Image.new("RGB", (1072, 1448), "white").save(panel_path)
            with self.assertRaises(MODULE.PanelError):
                MODULE.read_panel(panel_path, 2 * 1024 * 1024)

    def test_calendar_token_file_must_be_private(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            token = Path(temporary) / "calendar.token"
            token.write_text("x" * 48 + "\n", encoding="ascii")
            token.chmod(0o644)
            with self.assertRaises(MODULE.PanelError):
                MODULE.read_calendar_token(token)
            token.chmod(0o600)
            self.assertEqual(MODULE.read_calendar_token(token), "x" * 48)


if __name__ == "__main__":
    unittest.main()
