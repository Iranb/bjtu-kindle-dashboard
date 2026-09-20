from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "kindle" / "kindle-calendar"


class StandaloneCalendarPackageTests(unittest.TestCase):
    def run_config_parser(self, content: str) -> subprocess.CompletedProcess[str]:
        common = PACKAGE / "bin" / "common.sh"
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "calendar.conf"
            config.write_text(content, encoding="utf-8")
            return subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    (
                        '. "$1"; CONFIG_FILE=$2; load_config || exit $?; '
                        "printf '%s\\n' \"$CALENDAR_MODE\" \"$DAILY_REFRESH_HOUR\" "
                        '"$DAILY_REFRESH_MINUTE" "$HOLIDAY_REFRESH_SECONDS"'
                    ),
                    "sh",
                    str(common),
                    str(config),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

    def test_required_package_files_exist(self) -> None:
        for relative in (
            "calendar.conf.example",
            "config.xml",
            "menu.json",
            "install.sh",
            "bin/common.sh",
            "bin/daemon.sh",
            "bin/ensure-screensaver.sh",
            "bin/holiday-refresh.sh",
            "bin/update.sh",
            "bin/show.sh",
            "bin/control.sh",
            "upstart/kindle-calendar.conf",
            "THIRD_PARTY_NOTICES.md",
        ):
            self.assertTrue((PACKAGE / relative).is_file(), relative)

    def test_kual_manifest_and_menu(self) -> None:
        root = ET.parse(PACKAGE / "config.xml").getroot()
        self.assertEqual(root.findtext("information/id"), "kindle-calendar")
        self.assertEqual(root.findtext("information/name"), "Offline Calendar")
        self.assertEqual(root.findtext("information/version"), "1.1")
        menu = json.loads((PACKAGE / "menu.json").read_text(encoding="utf-8"))
        self.assertEqual(menu["items"][0]["name"], "Offline Calendar")
        actions = [item["action"] for item in menu["items"][0]["items"]]
        self.assertIn("bin/control.sh refresh", actions)
        self.assertIn("bin/control.sh disable", actions)

    def test_shell_is_posix_and_config_is_not_sourced(self) -> None:
        for script in [PACKAGE / "install.sh", *(PACKAGE / "bin").glob("*.sh")]:
            subprocess.run(["sh", "-n", str(script)], check=True)
        common = (PACKAGE / "bin/common.sh").read_text(encoding="utf-8")
        self.assertNotIn('. "$CONFIG_FILE"', common)
        self.assertNotIn("source ", common)
        self.assertNotIn("eval ", common)
        self.assertIn('unknown key: $KEY', common)

    def test_secrets_stay_out_of_usb_config_and_logs(self) -> None:
        config = (PACKAGE / "calendar.conf.example").read_text(encoding="utf-8")
        self.assertNotIn("URL", config)
        self.assertNotIn("TOKEN", config)
        update = (PACKAGE / "bin/update.sh").read_text(encoding="utf-8")
        self.assertNotIn('cat "$FEED_FILE"', update)
        deploy = (ROOT / "scripts" / "deploy_standalone_calendar.py").read_text(encoding="utf-8")
        self.assertIn('input=feed + "\\n"', deploy)

    def test_offline_mode_is_default_and_does_not_require_wifi(self) -> None:
        config = (PACKAGE / "calendar.conf.example").read_text(encoding="utf-8")
        self.assertIn("CALENDAR_MODE=offline", config)
        self.assertIn("HOLIDAY_REFRESH_SECONDS=604800", config)
        update = (PACKAGE / "bin/update.sh").read_text(encoding="utf-8")
        self.assertIn('if [ "$CALENDAR_MODE" = ics ]', update)
        daemon = (PACKAGE / "bin/daemon.sh").read_text(encoding="utf-8")
        self.assertIn('[ "$CALENDAR_MODE" = ics ]', daemon)
        holiday = (PACKAGE / "bin/holiday-refresh.sh").read_text(encoding="utf-8")
        self.assertIn("-holiday-only", holiday)
        self.assertIn('write_state "$NEXT_DUE_FILE"', holiday)

    def test_native_screensaver_integration_is_single_writer(self) -> None:
        common = (PACKAGE / "bin/common.sh").read_text(encoding="utf-8")
        self.assertIn("bjtu-native-screensaver/assets/panel-base.png", common)
        install = (PACKAGE / "install.sh").read_text(encoding="utf-8")
        control = (PACKAGE / "bin/control.sh").read_text(encoding="utf-8")
        self.assertIn("disabled competing BJTU dashboard updater", install)
        self.assertIn("stop_competing_dashboard", control)
        daemon = (PACKAGE / "bin/daemon.sh").read_text(encoding="utf-8")
        self.assertIn("! is_charging", daemon)

    def test_offline_config_parser_accepts_only_bounded_whitelist(self) -> None:
        valid = self.run_config_parser(
            "CALENDAR_MODE=offline\n"
            "DAILY_REFRESH_HOUR=0\n"
            "DAILY_REFRESH_MINUTE=5\n"
            "HOLIDAY_REFRESH_SECONDS=604800\n"
        )
        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertEqual(valid.stdout.splitlines(), ["offline", "0", "5", "604800"])

        for content in (
            "CALENDAR_MODE=remote\n",
            "DAILY_REFRESH_HOUR=24\n",
            "DAILY_REFRESH_HOUR=00\n",
            "DAILY_REFRESH_MINUTE=60\n",
            "HOLIDAY_REFRESH_SECONDS=60\n",
            "CALENDAR_MODE=offline\nCALENDAR_MODE=ics\n",
            "HOLIDAY_URL=https://example.invalid/data.json\n",
            "CALENDAR_MODE=$(touch-marker)\n",
        ):
            with self.subTest(content=content):
                result = self.run_config_parser(content)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("invalid config:", result.stderr)

    def test_daemon_has_network_rtc_and_unlock_cancellation(self) -> None:
        daemon = (PACKAGE / "bin/daemon.sh").read_text(encoding="utf-8")
        self.assertIn("connectionAvailable", daemon)
        self.assertIn("rtcWakeup", daemon)
        self.assertIn("abortSuspend", daemon)
        self.assertIn("outOfScreenSaver", daemon)
        self.assertIn("cancel_background_work", daemon)
        self.assertIn('kill "$UPDATE_PID"', daemon)
        self.assertIn('kill "$HOLIDAY_PID"', daemon)
        self.assertNotIn("powerButton", daemon)


if __name__ == "__main__":
    unittest.main()
