import importlib.util
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "install_macos_hpc_sync", ROOT / "scripts" / "install_macos_hpc_sync.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MacOSSyncInstallerTests(unittest.TestCase):
    def test_launch_agent_uses_watch_path_and_interval_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot = root / "snapshot.json"
            plist = MODULE.build_plist(
                home=root,
                python=root / "venv/bin/python3",
                app_dir=root / "app",
                runtime_dir=root,
                snapshot=snapshot,
                remote="https://github.com/example/repo.git",
                ssh_target="",
                ssh_path="safe/panel.png",
                branch="kindle-live",
                interval=300,
                orientation="portrait",
                publish_both=False,
                ssh_right_path="safe/panel-right.png",
            )
            self.assertEqual(plist["StartInterval"], 300)
            self.assertEqual(plist["WatchPaths"], [str(snapshot)])
            self.assertTrue(plist["RunAtLoad"])
            self.assertIn("--remote", plist["ProgramArguments"])
            self.assertNotIn("token", str(plist).lower())
            self.assertEqual(plist["ProgramArguments"][:2], ["/usr/bin/env", "-i"])
            self.assertNotIn("EnvironmentVariables", plist)

    def test_local_only_plist_omits_remote_argument(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plist = MODULE.build_plist(
                home=root,
                python=root / "python3",
                app_dir=root / "app",
                runtime_dir=root,
                snapshot=root / "snapshot.json",
                remote="",
                ssh_target="",
                ssh_path="safe/panel.png",
                branch="kindle-live",
                interval=300,
                orientation="portrait",
                publish_both=False,
                ssh_right_path="safe/panel-right.png",
            )
            self.assertNotIn("--remote", plist["ProgramArguments"])

    def test_ssh_edge_plist_contains_no_password_or_git_remote(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plist = MODULE.build_plist(
                home=root,
                python=root / "python3",
                app_dir=root / "app",
                runtime_dir=root,
                snapshot=root / "snapshot.json",
                remote="",
                ssh_target="kindle-edge",
                ssh_path="safe/panel.png",
                branch="kindle-live",
                interval=300,
                orientation="right",
                publish_both=True,
                ssh_right_path="safe/panel-right.png",
            )
            arguments = plist["ProgramArguments"]
            self.assertIn("--ssh-target", arguments)
            self.assertNotIn("--remote", arguments)
            self.assertNotIn("password", str(plist).lower())
            orientation_index = arguments.index("--orientation")
            self.assertEqual(arguments[orientation_index + 1], "right")
            self.assertIn("--publish-both", arguments)
            right_path_index = arguments.index("--ssh-right-path")
            self.assertEqual(arguments[right_path_index + 1], "safe/panel-right.png")

    def test_installer_rejects_unsafe_ssh_destination(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            MODULE.parse_args(
                ["--print-plist", "--ssh-target", "user@host"]
            )

    def test_calendar_publication_is_opt_in_and_ssh_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plist = MODULE.build_plist(
                home=root,
                python=root / "python3",
                app_dir=root / "app",
                runtime_dir=root,
                snapshot=root / "snapshot.json",
                remote="",
                ssh_target="kindle-edge",
                ssh_path="safe/panel.png",
                branch="kindle-live",
                interval=300,
                orientation="portrait",
                publish_both=True,
                ssh_right_path="safe/panel-right.png",
                publish_calendar=True,
                ssh_calendar_path="safe/calendar.png",
                ssh_calendar_right_path="safe/calendar-right.png",
            )
            arguments = plist["ProgramArguments"]
            self.assertIn("--publish-calendar", arguments)
            self.assertIn("--ssh-calendar-path", arguments)
            self.assertEqual(
                arguments[arguments.index("--calendar-hours") + 1], "1008"
            )
            self.assertEqual(
                arguments[arguments.index("--calendar-max-events") + 1], "84"
            )
            self.assertNotIn("Authorization", str(plist))
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            MODULE.parse_args(
                [
                    "--print-plist",
                    "--remote", "https://github.com/example/repo.git",
                    "--publish-calendar",
                    "--publish-both",
                ]
            )

    def test_calendar_helper_uses_eventkit_without_apple_events(self) -> None:
        installer = (ROOT / "scripts/install_macos_hpc_sync.py").read_text("utf-8")
        reader = (ROOT / "scripts/apple_calendar_eventkit.swift").read_text("utf-8")
        agenda = (ROOT / "scripts/apple_calendar_agenda.py").read_text("utf-8")
        self.assertIn('"EventKit"', installer)
        self.assertIn("NSCalendarsFullAccessUsageDescription", installer)
        self.assertIn("LSUIElement", installer)
        self.assertIn("EKEventStore", reader)
        self.assertIn("requestFullAccessToEvents", reader)
        self.assertIn('"--timeout",\n            "90"', installer)
        self.assertNotIn("osacompile", installer)
        self.assertNotIn("NSAppleEventsUsageDescription", installer)
        self.assertNotIn("osascript", agenda)
        self.assertNotIn('Application("Calendar")', agenda)


if __name__ == "__main__":
    unittest.main()
