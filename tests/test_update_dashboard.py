import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "update_dashboard", ROOT / "scripts" / "update_dashboard.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / "data" / "dashboard.json").read_text("utf-8"))

    def test_renders_pw3_grayscale_png(self):
        rendered = MODULE.Renderer(MODULE.validate(copy.deepcopy(self.data)), "data").render()
        self.assertEqual(rendered.size, (1072, 1448))
        self.assertEqual(rendered.mode, "L")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "dashboard.png"
            rendered.save(output)
            with Image.open(output) as reopened:
                self.assertEqual(reopened.size, (1072, 1448))
                self.assertEqual(reopened.mode, "L")

    def test_renders_right_landscape_as_native_framebuffer_png(self):
        data = MODULE.validate(copy.deepcopy(self.data))
        renderer = MODULE.RightLandscapeRenderer(data, "data")
        logical = renderer.render_logical()
        self.assertEqual(logical.size, (1448, 1072))
        rendered = MODULE.render_dashboard(data, "data", "right")
        self.assertEqual(rendered.size, (1072, 1448))
        self.assertEqual(rendered.mode, "L")

    def test_rejects_unknown_orientation(self):
        with self.assertRaises(MODULE.DashboardError):
            MODULE.render_dashboard(
                MODULE.validate(copy.deepcopy(self.data)), "data", "upside-down"
            )

    def test_rejects_impossible_gpu_count(self):
        invalid = copy.deepcopy(self.data)
        invalid["capacity"]["gpus_free"] = 33
        with self.assertRaises(MODULE.DashboardError):
            MODULE.validate(invalid)

    def test_rejects_unknown_account_status(self):
        invalid = copy.deepcopy(self.data)
        invalid["accounts"][0]["status"] = "BROKEN"
        with self.assertRaises(MODULE.DashboardError):
            MODULE.validate(invalid)


if __name__ == "__main__":
    unittest.main()
