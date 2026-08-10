import importlib.util
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
                branch="kindle-live",
                interval=300,
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
                branch="kindle-live",
                interval=300,
            )
            self.assertNotIn("--remote", plist["ProgramArguments"])


if __name__ == "__main__":
    unittest.main()
