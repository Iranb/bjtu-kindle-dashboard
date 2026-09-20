from __future__ import annotations

import json
import subprocess
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "kindle" / "kindle-calendar"


class StandaloneCalendarPackageTests(unittest.TestCase):
    def test_required_package_files_exist(self) -> None:
        for relative in (
            "calendar.conf.example",
            "config.xml",
            "menu.json",
            "install.sh",
            "bin/common.sh",
            "bin/daemon.sh",
            "bin/ensure-screensaver.sh",
            "bin/update.sh",
            "bin/show.sh",
            "bin/control.sh",
            "upstart/kindle-calendar.conf",
        ):
            self.assertTrue((PACKAGE / relative).is_file(), relative)

    def test_kual_manifest_and_menu(self) -> None:
        root = ET.parse(PACKAGE / "config.xml").getroot()
        self.assertEqual(root.findtext("information/id"), "kindle-calendar")
        menu = json.loads((PACKAGE / "menu.json").read_text(encoding="utf-8"))
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

    def test_daemon_has_network_rtc_and_unlock_cancellation(self) -> None:
        daemon = (PACKAGE / "bin/daemon.sh").read_text(encoding="utf-8")
        self.assertIn("connectionAvailable", daemon)
        self.assertIn("rtcWakeup", daemon)
        self.assertIn("abortSuspend", daemon)
        self.assertIn("outOfScreenSaver", daemon)
        self.assertIn("cancel_active_update", daemon)
        self.assertNotIn("powerButton", daemon)


if __name__ == "__main__":
    unittest.main()
