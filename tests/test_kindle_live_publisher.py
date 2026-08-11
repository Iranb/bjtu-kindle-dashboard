import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "publish_kindle_live", ROOT / "scripts" / "publish_kindle_live.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


class KindleLivePublisherTests(unittest.TestCase):
    def test_publish_is_idempotent_and_keeps_one_remote_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            remote = root / "remote.git"
            worktree = root / "publisher"
            image = root / "panel.png"
            git(root, "init", "--bare", "--quiet", str(remote))

            Image.new("L", (1072, 1448), 255).save(image)
            first = MODULE.publish(
                image=image, worktree=worktree, remote=str(remote)
            )
            second = MODULE.publish(
                image=image, worktree=worktree, remote=str(remote)
            )
            self.assertTrue(first["changed"])
            self.assertFalse(second["changed"])

            Image.new("L", (1072, 1448), 0).save(image)
            third = MODULE.publish(
                image=image, worktree=worktree, remote=str(remote)
            )
            self.assertTrue(third["changed"])
            self.assertNotEqual(first["image_sha256"], third["image_sha256"])
            self.assertEqual(
                git(remote, "rev-list", "--count", "refs/heads/kindle-live"), "1"
            )
            names = set(
                git(remote, "ls-tree", "-r", "--name-only", "refs/heads/kindle-live")
                .splitlines()
            )
            self.assertEqual(names, MODULE.ALLOWED_REMOTE_FILES)

            manifest = json.loads(
                git(
                    remote,
                    "show",
                    "refs/heads/kindle-live:assets/manifest.json",
                )
            )
            self.assertEqual(manifest["sha256"], third["image_sha256"])
            self.assertNotIn("source", manifest)

    def test_rejects_credentials_and_wrong_image_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "panel.png"
            Image.new("RGB", (1072, 1448), "white").save(image)
            with self.assertRaises(MODULE.PublishError):
                MODULE.validate_image(image, 2 * 1024 * 1024)
            with self.assertRaises(MODULE.PublishError):
                MODULE.validate_remote("https://user:secret@example.invalid/repo.git")

    def test_first_push_failure_is_retryable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            remote = root / "remote.git"
            worktree = root / "publisher"
            image = root / "panel.png"
            git(root, "init", "--bare", "--quiet", str(remote))
            Image.new("L", (1072, 1448), 128).save(image)

            hook = remote / "hooks" / "pre-receive"
            hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            hook.chmod(0o755)
            with self.assertRaises(MODULE.PublishError):
                MODULE.publish(image=image, worktree=worktree, remote=str(remote))

            hook.unlink()
            retried = MODULE.publish(
                image=image, worktree=worktree, remote=str(remote)
            )
            self.assertTrue(retried["changed"])
            self.assertEqual(
                git(remote, "rev-list", "--count", "refs/heads/kindle-live"), "1"
            )

    def test_refuses_unmarked_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "unrelated.txt").write_text("keep", encoding="utf-8")
            with self.assertRaises(MODULE.PublishError):
                MODULE.prepare_worktree(root, "https://example.invalid/repo.git")


if __name__ == "__main__":
    unittest.main()
