from pathlib import Path
import unittest

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
UPDATER = ROOT / "kindle" / "bjtu-dashboard-updater"


class KindleUpdaterTests(unittest.TestCase):
    def test_required_payload_files_exist(self) -> None:
        required = [
            "bin/common.sh",
            "bin/fetch-panel.sh",
            "bin/network-window.sh",
            "bin/updater-daemon.sh",
            "bin/control.sh",
            "upstart/bjtu-dashboard-updater.conf",
            "update.conf.example",
            "install.sh",
            "menu.json",
        ]
        for relative in required:
            self.assertTrue((UPDATER / relative).is_file(), relative)

    def test_shell_scripts_are_unix_text(self) -> None:
        scripts = list((UPDATER / "bin").glob("*.sh")) + [UPDATER / "install.sh"]
        for script in scripts:
            content = script.read_bytes()
            self.assertTrue(content.startswith(b"#!/bin/sh\n"), script.name)
            self.assertNotIn(b"\r\n", content, script.name)
        self.assertNotIn(b"\r\n", (UPDATER / "update.conf.example").read_bytes())

    def test_validated_power_sequence_is_present(self) -> None:
        daemon = (UPDATER / "bin" / "updater-daemon.sh").read_text("utf-8")
        window = (UPDATER / "bin" / "network-window.sh").read_text("utf-8")
        self.assertIn('case "$LEVEL"', daemon)
        self.assertIn('1)', daemon)
        self.assertIn("rtcWakeup", daemon)
        self.assertIn("abortSuspend", daemon)
        self.assertIn('SCHEDULED + WAKE_EARLY_TOLERANCE_SECONDS', daemon)
        self.assertIn("CONNECTED", window)
        self.assertNotIn("wifid enable", daemon)

    def test_fetcher_validates_and_serializes_image_updates(self) -> None:
        common = (UPDATER / "bin" / "common.sh").read_text("utf-8")
        fetcher = (UPDATER / "bin" / "fetch-panel.sh").read_text("utf-8")
        self.assertIn("FETCH_LOCK_DIR", common)
        self.assertIn('mkdir "$FETCH_LOCK_DIR"', fetcher)
        self.assertIn("validate_png", fetcher)
        self.assertIn("application/vnd.github.raw+json", fetcher)
        self.assertIn("sha256sum", fetcher)
        self.assertIn('mv -f "$INCOMING" "$ASSET"', fetcher)

    def test_public_config_contains_no_credentials(self) -> None:
        config = (UPDATER / "update.conf.example").read_text("utf-8").lower()
        self.assertIn("https://", config)
        self.assertIn("api.github.com", config)
        self.assertIn("?ref=main", config)
        self.assertNotIn("authorization:", config)
        self.assertNotIn("bearer ", config)

    def test_deployer_targets_the_independent_extension(self) -> None:
        deployer = (ROOT / "scripts" / "deploy_kindle_updater.py").read_text("utf-8")
        self.assertIn('REMOTE_PARENT = "/mnt/us/extensions"', deployer)
        self.assertIn('REMOTE_DIR = f"{REMOTE_PARENT}/bjtu-dashboard-updater"', deployer)
        self.assertIn("install.sh install", deployer)

    def test_published_panel_asset_matches_the_device_contract(self) -> None:
        asset = ROOT / "assets" / "panel-base.png"
        self.assertTrue(asset.is_file())
        with Image.open(asset) as image:
            self.assertEqual(image.size, (1072, 1448))
            self.assertEqual(image.mode, "L")


if __name__ == "__main__":
    unittest.main()
