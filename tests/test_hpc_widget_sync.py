import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "sync_hpc_widget", ROOT / "scripts" / "sync_hpc_widget.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def sample_snapshot() -> dict:
    accounts = []
    guardian_accounts = {}
    for index, name in enumerate(("secret-z", "secret-a", "secret-f", "secret-b", "secret-e", "secret-c")):
        accounts.append(
            {
                "name": name,
                "has_token": True,
                "error": None,
                "summary": {
                    "running": 1 if index == 0 else 0,
                    "pending": 1 if index == 1 else 0,
                },
                "jobs": [{"job_id": f"private-{index}", "name": "private-job"}],
            }
        )
        guardian_accounts[name] = {
            "status": "valid",
            "attention_required": False,
            "needs_visible_login": False,
        }
    guardian_accounts["secret-c"]["needs_visible_login"] = True
    return {
        "version": 1,
        "written_at": datetime.now(timezone.utc).isoformat(),
        "returncode": 0,
        "error": None,
        "stale_payload": False,
        "payload": {
            "checked_at_local": "2026-08-10T11:37:50",
            "accounts": accounts,
            "cluster_resources": {
                "error": None,
                "summary": {
                    "gpu_free": 27,
                    "gpu_total": 32,
                    "cpu_free": 188,
                    "cpu_total": 192,
                },
                "nodes": [
                    {
                        "name": f"private-host-{index}",
                        "state": "IDLE" if index > 1 else "MIXED",
                        "gpu_free": 8 if index > 1 else 5,
                        "gpu_total": 8,
                    }
                    for index in (4, 2, 3, 1)
                ],
            },
        },
        "guardian": {"accounts": guardian_accounts},
    }


class HPCWidgetSyncTests(unittest.TestCase):
    def test_snapshot_is_anonymized_and_mapped_to_dashboard(self) -> None:
        dashboard = MODULE.dashboard_from_snapshot(sample_snapshot())
        encoded = json.dumps(dashboard)
        self.assertNotIn("secret-", encoded)
        self.assertNotIn("private-job", encoded)
        self.assertNotIn("private-host", encoded)
        self.assertEqual(
            [row["name"] for row in dashboard["accounts"]],
            [f"ACCOUNT {letter}" for letter in "ABCDEF"],
        )
        self.assertEqual([row["name"] for row in dashboard["nodes"]], ["GPU01", "GPU02", "GPU03", "GPU04"])
        self.assertEqual(dashboard["capacity"]["gpus_free"], 27)
        self.assertEqual(dashboard["capacity"]["jobs_running"], 1)
        self.assertEqual(dashboard["capacity"]["jobs_queued"], 1)
        self.assertIn("WAITING", [row["status"] for row in dashboard["accounts"]])
        self.assertIn("SIGN-IN", [row["status"] for row in dashboard["accounts"]])

    def test_stale_source_is_visible_and_not_healthy(self) -> None:
        snapshot = sample_snapshot()
        snapshot["written_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        dashboard = MODULE.dashboard_from_snapshot(snapshot, max_age_seconds=300)
        self.assertIn("STALE", dashboard["cluster"]["subtitle"])
        self.assertFalse(dashboard["capacity"]["all_systems_online"])

    def test_missing_token_is_not_reported_as_healthy(self) -> None:
        snapshot = sample_snapshot()
        del snapshot["payload"]["accounts"][0]["has_token"]
        dashboard = MODULE.dashboard_from_snapshot(snapshot)
        self.assertIn("SIGN-IN", [row["status"] for row in dashboard["accounts"]])

    def test_sync_renders_once_and_skips_unchanged_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_path = root / "snapshot.json"
            image_path = root / "panel.png"
            data_path = root / "dashboard.json"
            state_path = root / "state.json"
            snapshot_path.write_text(json.dumps(sample_snapshot()), encoding="utf-8")
            args = MODULE.parse_args(
                [
                    "--snapshot",
                    str(snapshot_path),
                    "--image-output",
                    str(image_path),
                    "--data-output",
                    str(data_path),
                    "--state-file",
                    str(state_path),
                ]
            )
            first = MODULE.sync_once(args)
            first_mtime = image_path.stat().st_mtime_ns
            second = MODULE.sync_once(args)
            self.assertTrue(first["changed"])
            self.assertFalse(second["changed"])
            self.assertEqual(image_path.stat().st_mtime_ns, first_mtime)
            with Image.open(image_path) as image:
                self.assertEqual(image.size, (1072, 1448))
                self.assertEqual(image.mode, "L")


if __name__ == "__main__":
    unittest.main()
