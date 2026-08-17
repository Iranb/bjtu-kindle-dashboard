from pathlib import Path
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
UPDATER = ROOT / "kindle" / "bjtu-dashboard-updater"


class KindleUpdaterTests(unittest.TestCase):
    def run_config_parser(self, content: str) -> subprocess.CompletedProcess[str]:
        common = UPDATER / "bin" / "common.sh"
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "update.conf"
            config.write_text(content, encoding="utf-8")
            return subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    (
                        '. "$1"; CONFIG_FILE=$2; load_config || exit $?; '
                        "printf '%s\\n' \"$UPDATE_URL\" \"$BATTERY_INTERVAL_SECONDS\" "
                        '"$LOW_BATTERY_PERCENT" "$ALLOW_HTTP" "$DISPLAY_ORIENTATION" '
                        '"$UPDATE_URL_RIGHT"'
                    ),
                    "sh",
                    str(common),
                    str(config),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

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
            "config.xml",
            "menu.json",
            "integration/render-panel.sh",
        ]
        for relative in required:
            self.assertTrue((UPDATER / relative).is_file(), relative)

    def test_shell_scripts_are_unix_text(self) -> None:
        scripts = list((UPDATER / "bin").glob("*.sh")) + [
            UPDATER / "install.sh",
            UPDATER / "integration" / "render-panel.sh",
        ]
        for script in scripts:
            content = script.read_bytes()
            self.assertTrue(content.startswith(b"#!/bin/sh\n"), script.name)
            self.assertNotIn(b"\r\n", content, script.name)
        self.assertNotIn(b"\r\n", (UPDATER / "update.conf.example").read_bytes())

    def test_validated_power_sequence_is_present(self) -> None:
        daemon = (UPDATER / "bin" / "updater-daemon.sh").read_text("utf-8")
        window = (UPDATER / "bin" / "network-window.sh").read_text("utf-8")
        control = (UPDATER / "bin" / "control.sh").read_text("utf-8")
        self.assertIn('case "$LEVEL"', daemon)
        self.assertIn('1)', daemon)
        self.assertIn("rtcWakeup", daemon)
        self.assertIn("abortSuspend", daemon)
        self.assertIn('SCHEDULED + WAKE_EARLY_TOLERANCE_SECONDS', daemon)
        self.assertIn("CONNECTED", window)
        self.assertNotIn("wifid enable", daemon)
        self.assertNotIn("powerButton", daemon)
        self.assertNotIn("powerButton", control)

    def test_charging_keep_awake_is_bounded_and_user_cancellable(self) -> None:
        daemon = (UPDATER / "bin" / "updater-daemon.sh").read_text("utf-8")
        self.assertIn('is_charging && [ "$(power_state)" = "screenSaver" ]', daemon)
        self.assertIn('suspendGrace "$KEEP_AWAKE_GRACE_SECONDS"', daemon)
        self.assertIn('sleep "$KEEP_AWAKE_RENEW_SECONDS"', daemon)
        self.assertIn("*outOfScreenSaver*", daemon)
        self.assertIn("release_keep_awake", daemon)

    def test_fetcher_validates_and_serializes_image_updates(self) -> None:
        common = (UPDATER / "bin" / "common.sh").read_text("utf-8")
        fetcher = (UPDATER / "bin" / "fetch-panel.sh").read_text("utf-8")
        self.assertIn("FETCH_LOCK_DIR", common)
        self.assertIn('mkdir "$FETCH_LOCK_DIR"', fetcher)
        self.assertIn("validate_png", fetcher)
        self.assertIn("application/vnd.github.raw+json", fetcher)
        self.assertIn("sha256sum", fetcher)
        self.assertIn('mv -f "$INCOMING" "$ASSET"', fetcher)
        self.assertIn(
            'write_state "$ORIENTATION_FILE" "$DISPLAY_ORIENTATION"', fetcher
        )
        self.assertIn(
            '[ "$CURRENT_ORIENTATION" = "$DISPLAY_ORIENTATION" ] && [ -f "$ETAG_FILE" ]',
            fetcher,
        )
        self.assertIn('fail "orientation_not_refetched"', fetcher)

    def test_usb_config_is_parsed_as_whitelisted_data(self) -> None:
        common = (UPDATER / "bin" / "common.sh").read_text("utf-8")
        self.assertNotIn('. "$CONFIG_FILE"', common)
        self.assertNotIn("eval ", common)

        result = self.run_config_parser(
            "# settings\n"
            'UPDATE_URL="https://api.github.com/repos/example/project/contents/panel.png?ref=main"\n'
            'UPDATE_URL_RIGHT="https://api.github.com/repos/example/project/contents/panel-right.png?ref=main"\n'
            "BATTERY_INTERVAL_SECONDS=7200\n"
            "LOW_BATTERY_PERCENT=15\n"
            "ALLOW_HTTP=0\n"
            "DISPLAY_ORIENTATION=right\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "https://api.github.com/repos/example/project/contents/panel.png?ref=main",
                "7200",
                "15",
                "0",
                "right",
                "https://api.github.com/repos/example/project/contents/panel-right.png?ref=main",
            ],
        )

    def test_usb_config_rejects_unknown_duplicate_and_out_of_range_values(self) -> None:
        invalid_configs = [
            "RUN_COMMAND=anything\n",
            "ALLOW_HTTP=0\nALLOW_HTTP=1\n",
            "LOW_BATTERY_PERCENT=101\n",
            "DOWNLOAD_TIMEOUT_SECONDS=-1\n",
            "DOWNLOAD_TIMEOUT_SECONDS=012\n",
            "MAX_IMAGE_BYTES=999999999999999999999999\n",
            " BATTERY_INTERVAL_SECONDS=3600\n",
            "UPDATE_URL=https://example.invalid/a b.png\n",
            "UPDATE_URL=https://example.invalid/$(touch-marker)\n",
            "UPDATE_URL_RIGHT=https://example.invalid/a b.png\n",
            "KEEP_AWAKE_GRACE_SECONDS=120\nKEEP_AWAKE_RENEW_SECONDS=120\n",
            "DISPLAY_ORIENTATION=left\n",
            "DISPLAY_ORIENTATION=right;touch-marker\n",
        ]
        for config in invalid_configs:
            with self.subTest(config=config):
                result = self.run_config_parser(config)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("invalid config:", result.stderr)

    def test_usb_config_never_executes_shell_syntax(self) -> None:
        common = UPDATER / "bin" / "common.sh"
        with tempfile.TemporaryDirectory() as temp_dir:
            marker = Path(temp_dir) / "executed"
            config = Path(temp_dir) / "update.conf"
            config.write_text(
                f'UPDATE_URL="$(touch {marker})"\n',
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    '. "$1"; CONFIG_FILE=$2; load_config',
                    "sh",
                    str(common),
                    str(config),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(marker.exists())

    def test_every_device_shell_script_passes_posix_syntax_check(self) -> None:
        scripts = list((UPDATER / "bin").glob("*.sh")) + [
            UPDATER / "install.sh",
            UPDATER / "integration" / "render-panel.sh",
        ]
        for script in scripts:
            with self.subTest(script=script.name):
                result = subprocess.run(
                    ["/bin/sh", "-n", str(script)],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_public_config_contains_no_credentials(self) -> None:
        config = (UPDATER / "update.conf.example").read_text("utf-8").lower()
        self.assertIn("https://", config)
        self.assertIn("api.github.com", config)
        self.assertIn("?ref=main", config)
        self.assertNotIn("authorization:", config)
        self.assertNotIn("bearer ", config)

    def test_kual_manifest_registers_the_dynamic_menu(self) -> None:
        root = ET.parse(UPDATER / "config.xml").getroot()
        self.assertEqual(root.tag, "extension")
        self.assertEqual(root.findtext("information/id"), "bjtu-dashboard-updater")
        menu = root.find("menus/menu")
        self.assertIsNotNone(menu)
        assert menu is not None
        self.assertEqual(menu.attrib.get("type"), "json")
        self.assertEqual(menu.attrib.get("dynamic"), "true")
        self.assertEqual(menu.text, "menu.json")

    def test_deployer_targets_the_independent_extension(self) -> None:
        deployer = (ROOT / "scripts" / "deploy_kindle_updater.py").read_text("utf-8")
        self.assertIn('REMOTE_PARENT = "/mnt/us/extensions"', deployer)
        self.assertIn('REMOTE_DIR = f"{REMOTE_PARENT}/bjtu-dashboard-updater"', deployer)
        self.assertIn('["scp", "-O", "-r"', deployer)
        self.assertIn("install.sh install", deployer)

    def test_orientation_switch_is_bounded_and_hook_skips_portrait_overlay(self) -> None:
        control = (UPDATER / "bin" / "control.sh").read_text("utf-8")
        hook = (UPDATER / "integration" / "render-panel.sh").read_text("utf-8")
        menu = (UPDATER / "menu.json").read_text("utf-8")
        self.assertIn('portrait|right)', control)
        self.assertIn('orientation portrait', menu)
        self.assertIn('orientation right', menu)
        self.assertIn('orientation toggle', menu)
        self.assertIn('toggle_orientation()', control)
        self.assertIn('right) set_orientation portrait', control)
        self.assertIn('*) set_orientation right', control)
        self.assertIn('portrait|right) CURRENT_ORIENTATION=', control)
        self.assertIn('if [ "$ORIENTATION" = "portrait" ]', hook)
        self.assertNotIn("fbdepth", hook)

    def test_portrait_clock_uses_explicit_utc_plus_eight(self) -> None:
        hook = (UPDATER / "integration" / "render-panel.sh").read_text("utf-8")
        self.assertIn('LOCKSCREEN_TZ="CST-8"', hook)
        self.assertIn('TZ="$LOCKSCREEN_TZ" date \'+%H:%M\'', hook)
        self.assertIn('TZ="$LOCKSCREEN_TZ" LC_ALL=C date', hook)
        self.assertNotIn("TIME_TEXT=$(date '+%H:%M')", hook)

    def test_published_panel_asset_matches_the_device_contract(self) -> None:
        for name in ("panel-base.png", "panel-base-right.png"):
            with self.subTest(name=name):
                asset = ROOT / "assets" / name
                self.assertTrue(asset.is_file())
                with Image.open(asset) as image:
                    self.assertEqual(image.size, (1072, 1448))
                    self.assertEqual(image.mode, "L")


if __name__ == "__main__":
    unittest.main()
