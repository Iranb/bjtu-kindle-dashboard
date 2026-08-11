import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "publish_kindle_ssh", ROOT / "scripts" / "publish_kindle_ssh.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class KindleSSHPublisherTests(unittest.TestCase):
    def test_accepts_credential_free_alias_and_relative_path(self) -> None:
        self.assertEqual(MODULE.validate_target("kindle-edge"), "kindle-edge")
        self.assertEqual(
            MODULE.validate_remote_path(MODULE.DEFAULT_REMOTE_PATH),
            MODULE.DEFAULT_REMOTE_PATH,
        )
        self.assertEqual(
            MODULE.validate_remote_path("safe/path/panel-base.png"),
            "safe/path/panel-base.png",
        )

    def test_rejects_shell_syntax_credentials_and_traversal(self) -> None:
        for target in ("user@host", "host;touch", "-oProxyCommand=x", "host name"):
            with self.subTest(target=target), self.assertRaises(MODULE.PublishError):
                MODULE.validate_target(target)
        for remote_path in (
            "/absolute/panel.png",
            "../panel.png",
            "safe/../../panel.png",
            "safe path/panel.png",
            "safe;touch/panel.png",
        ):
            with self.subTest(remote_path=remote_path), self.assertRaises(
                MODULE.PublishError
            ):
                MODULE.validate_remote_path(remote_path)


if __name__ == "__main__":
    unittest.main()
