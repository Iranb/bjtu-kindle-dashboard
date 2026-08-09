#!/usr/bin/env python3
"""Render and optionally deploy the BJTU Kindle cluster dashboard.

The input is a small JSON document. The output is a 1072x1448 8-bit
grayscale PNG suitable for a Kindle Paperwhite 3 and FBInk.
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1072
HEIGHT = 1448
WHITE = 255
DARK = 16
MID = 119

DEFAULT_REMOTE_IMAGE = (
    "/mnt/us/extensions/bjtu-native-screensaver/assets/panel-base.png"
)
DEFAULT_REMOTE_RENDER = (
    "/mnt/us/extensions/bjtu-native-screensaver/bin/render-panel.sh"
)


FONT_CANDIDATES = {
    "sans": [
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    ],
    "sans_bold": [
        Path(r"C:\Windows\Fonts\arialbd.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ],
    "serif": [
        Path(r"C:\Windows\Fonts\georgia.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
        Path("/System/Library/Fonts/Supplemental/Georgia.ttf"),
    ],
}


class DashboardError(ValueError):
    """Raised when input dashboard data is invalid."""


def require_int(value: Any, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DashboardError(f"{name} must be an integer")
    if value < minimum:
        raise DashboardError(f"{name} must be >= {minimum}")
    return value


def require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DashboardError(f"{name} must be a non-empty string")
    return value.strip().upper()


def validate(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise DashboardError("root JSON value must be an object")

    cluster = data.get("cluster")
    if not isinstance(cluster, dict):
        raise DashboardError("cluster must be an object")
    cluster["name"] = require_text(cluster.get("name"), "cluster.name")
    cluster["subtitle"] = require_text(
        cluster.get("subtitle"), "cluster.subtitle"
    )

    capacity = data.get("capacity")
    if not isinstance(capacity, dict):
        raise DashboardError("capacity must be an object")
    for key in ("gpus_free", "gpus_total", "cpu_cores_free", "jobs_running", "jobs_queued"):
        capacity[key] = require_int(capacity.get(key), f"capacity.{key}")
    if capacity["gpus_total"] < 1:
        raise DashboardError("capacity.gpus_total must be >= 1")
    if capacity["gpus_free"] > capacity["gpus_total"]:
        raise DashboardError("capacity.gpus_free cannot exceed capacity.gpus_total")
    capacity["all_systems_online"] = bool(capacity.get("all_systems_online", True))

    nodes = data.get("nodes")
    if not isinstance(nodes, list) or len(nodes) != 4:
        raise DashboardError("nodes must contain exactly four entries")
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            raise DashboardError(f"nodes[{index}] must be an object")
        node["name"] = require_text(node.get("name"), f"nodes[{index}].name")
        node["state"] = require_text(node.get("state"), f"nodes[{index}].state")
        node["free"] = require_int(node.get("free"), f"nodes[{index}].free")
        node["total"] = require_int(node.get("total"), f"nodes[{index}].total", 1)
        if node["free"] > node["total"]:
            raise DashboardError(f"nodes[{index}].free cannot exceed total")

    accounts = data.get("accounts")
    if not isinstance(accounts, list) or len(accounts) != 6:
        raise DashboardError("accounts must contain exactly six entries")
    allowed_statuses = {"HEALTHY", "WAITING", "SIGN-IN"}
    for index, account in enumerate(accounts):
        if not isinstance(account, dict):
            raise DashboardError(f"accounts[{index}] must be an object")
        account["name"] = require_text(
            account.get("name"), f"accounts[{index}].name"
        )
        account["status"] = require_text(
            account.get("status"), f"accounts[{index}].status"
        )
        if account["status"] not in allowed_statuses:
            raise DashboardError(
                f"accounts[{index}].status must be HEALTHY, WAITING, or SIGN-IN"
            )
        account["running"] = require_int(
            account.get("running"), f"accounts[{index}].running"
        )
        account["queued"] = require_int(
            account.get("queued"), f"accounts[{index}].queued"
        )

    header = data.setdefault("header", {})
    if not isinstance(header, dict):
        raise DashboardError("header must be an object")
    header["time"] = str(header.get("time", "14:30"))
    header["date"] = str(header.get("date", "SUN . AUG 9")).upper()
    header["battery"] = require_int(header.get("battery", 99), "header.battery")
    if header["battery"] > 100:
        raise DashboardError("header.battery cannot exceed 100")
    return data


class Renderer:
    def __init__(self, data: dict[str, Any], header_mode: str) -> None:
        self.data = data
        self.header_mode = header_mode
        self.image = Image.new("L", (WIDTH, HEIGHT), WHITE)
        self.draw = ImageDraw.Draw(self.image)
        self._fonts: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}

    def font(self, family: str, size: int) -> ImageFont.FreeTypeFont:
        key = (family, size)
        if key in self._fonts:
            return self._fonts[key]
        for candidate in FONT_CANDIDATES[family]:
            if candidate.is_file():
                loaded = ImageFont.truetype(str(candidate), size=size)
                self._fonts[key] = loaded
                return loaded
        raise DashboardError(
            f"no font found for {family}; install Arial/Georgia, Liberation, or DejaVu fonts"
        )

    def text(
        self,
        xy: tuple[float, float],
        value: Any,
        size: int,
        family: str = "sans",
        anchor: str = "ls",
        fill: int = DARK,
        spacing: float = 0,
        underline: bool = False,
    ) -> None:
        rendered = str(value)
        font = self.font(family, size)
        x, y = xy
        if spacing <= 0:
            self.draw.text((x, y), rendered, font=font, fill=fill, anchor=anchor)
            width = self.draw.textlength(rendered, font=font)
            start_x = x
            if anchor.startswith("m"):
                start_x -= width / 2
            elif anchor.startswith("r"):
                start_x -= width
        else:
            widths = [self.draw.textlength(char, font=font) for char in rendered]
            width = sum(widths) + spacing * max(0, len(rendered) - 1)
            start_x = x
            if anchor.startswith("m"):
                start_x -= width / 2
            elif anchor.startswith("r"):
                start_x -= width
            cursor = start_x
            for char, char_width in zip(rendered, widths):
                self.draw.text((cursor, y), char, font=font, fill=fill, anchor="ls")
                cursor += char_width + spacing
        if underline:
            self.draw.line((start_x, y + 4, start_x + width, y + 4), fill=fill, width=2)

    def rule(self, xy: tuple[int, int, int, int], width: int = 2, soft: bool = False) -> None:
        self.draw.line(xy, fill=MID if soft else DARK, width=width)

    def render(self) -> Image.Image:
        self.draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), fill=WHITE)
        self.draw.rectangle((2, 2, WIDTH - 3, HEIGHT - 3), outline=DARK, width=4)
        self.header()
        self.capacity()
        self.nodes()
        self.accounts()
        return self.image

    def header(self) -> None:
        cluster = self.data["cluster"]
        self.draw.rectangle((50, 55, 95, 97), outline=DARK, width=6)
        self.draw.rectangle((64, 67, 82, 85), fill=DARK)
        self.text((116, 76), cluster["name"], 30, "sans_bold", spacing=2.2)
        self.text((117, 101), cluster["subtitle"], 17, spacing=1.7)

        self.draw.rectangle((851, 66, 904, 89), outline=DARK, width=5)
        self.draw.rectangle((904, 72, 910, 83), fill=DARK)
        self.draw.rectangle((857, 72, 897, 83), fill=DARK)

        if self.header_mode != "blank":
            header = self.data["header"]
            if self.header_mode == "now":
                current = datetime.now()
                time_value = current.strftime("%H:%M")
                date_value = current.strftime("%a . %b %d").upper().replace(" 0", " ")
            else:
                time_value = header["time"]
                date_value = header["date"]
            self.text((762, 80), time_value, 42, "sans_bold", "ms")
            self.text((762, 108), date_value, 18, anchor="ms", spacing=1.7)
            self.text((923, 76), f"{header['battery']}%", 29, "sans_bold")
            self.text((923, 101), "BATTERY", 17, spacing=1.8)
        self.rule((50, 138, 1022, 138), width=4)

    def capacity(self) -> None:
        cap = self.data["capacity"]
        self.text((50, 190), "LIVE CAPACITY", 20, spacing=1.4)
        if cap["all_systems_online"]:
            self.draw.ellipse((319, 175, 333, 189), outline=DARK, width=4)
            status = "ALL SYSTEMS ONLINE"
        else:
            self.draw.ellipse((319, 175, 333, 189), fill=DARK)
            status = "ATTENTION REQUIRED"
        self.text((342, 190), status, 19, spacing=1.2)
        self.rule((50, 208, 582, 208), soft=True)

        self.text((55, 361), cap["gpus_free"], 151, "serif")
        self.text((458, 369), f"/ {cap['gpus_total']}", 62, "serif")
        self.rule((50, 400, 582, 400), width=4)
        self.text((50, 447), "GPUs FREE", 35, "sans_bold", spacing=1.1)
        percent = cap["gpus_free"] / cap["gpus_total"] * 100
        self.text((582, 447), f"{percent:.1f}% AVAILABLE", 19, anchor="rs", spacing=1.5)

        self.rule((630, 172, 630, 456), width=4)
        stats = [
            (225, 258, cap["cpu_cores_free"], "CPU CORES FREE"),
            (329, 357, cap["jobs_running"], "JOBS RUNNING"),
            (420, 456, cap["jobs_queued"], "JOB QUEUED"),
        ]
        for baseline, line_y, number, label in stats:
            self.text((665, baseline), number, 58 if baseline == 225 else 56, "serif")
            self.text((1022, baseline - 5), label, 20, anchor="rs", spacing=1.2)
            self.rule((665, line_y, 1022, line_y), soft=True)

        used = cap["gpus_total"] - cap["gpus_free"]
        self.text((50, 506), "GPU CAPACITY", 22, "sans_bold", spacing=1.3)
        self.text((1022, 506), f"USED {used}    FREE {cap['gpus_free']}", 20, anchor="rs", spacing=1.0)
        self.blocks(50, 524, 972, 33, cap["gpus_total"], used, gap=3)
        self.rule((50, 589, 1022, 589), width=6)

    def blocks(
        self,
        x: int,
        y: int,
        total_width: int,
        height: int,
        total: int,
        used: int,
        gap: int,
    ) -> None:
        block_width = (total_width - gap * (total - 1)) / total
        for index in range(total):
            left = round(x + index * (block_width + gap))
            right = round(left + block_width)
            box = (left, y, right, y + height)
            if index < used:
                self.draw.rectangle(box, fill=DARK)
            else:
                self.draw.rectangle(box, fill=WHITE, outline=DARK, width=2)

    def nodes(self) -> None:
        self.text((50, 646), "NODE AVAILABILITY", 36, spacing=2.4)
        self.draw.rectangle((842, 630, 856, 645), fill=DARK)
        self.text((865, 646), "USED", 17)
        self.draw.rectangle((945, 630, 959, 645), fill=WHITE, outline=DARK, width=2)
        self.text((968, 646), "FREE", 17)
        self.rule((50, 670, 1022, 670), soft=True)

        row_baselines = [701, 763, 825, 887]
        row_lines = [732, 794, 856]
        for index, (node, baseline) in enumerate(zip(self.data["nodes"], row_baselines)):
            self.text((50, baseline), node["name"], 27, "sans_bold")
            self.text((50, baseline + 24), node["state"], 18, spacing=1.5)
            used = node["total"] - node["free"]
            self.blocks(322, baseline - 11, 506, 23, node["total"], used, gap=7)
            self.text((940, baseline + 17), node["free"], 47, "serif", anchor="rs")
            self.text((950, baseline + 15), f"/ {node['total']} FREE", 17)
            if index < len(row_lines):
                self.rule((50, row_lines[index], 1022, row_lines[index]), soft=True)
        self.rule((50, 945, 1022, 945), width=6)

    def status_marker(self, x: int, y: int, status: str) -> None:
        if status == "HEALTHY":
            self.draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=WHITE, outline=DARK, width=2)
        elif status == "WAITING":
            self.draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=DARK, outline=DARK, width=2)
            self.draw.pieslice((x - 8, y - 8, x + 8, y + 8), 90, 270, fill=WHITE)
            self.draw.ellipse((x - 8, y - 8, x + 8, y + 8), outline=DARK, width=2)
        else:
            self.draw.ellipse((x - 9, y - 9, x + 9, y + 9), fill=DARK)

    def accounts(self) -> None:
        self.text((50, 1007), "ACCOUNT ACTIVITY", 40, spacing=2.6)
        self.text((1022, 1005), "6 ACCOUNTS", 19, anchor="rs", spacing=1.5)
        self.rule((50, 1037, 1022, 1037), soft=True)
        self.rule((555, 1037, 555, 1397), soft=True)

        name_baselines = [1084, 1204, 1324]
        detail_baselines = [1123, 1243, 1363]
        separators = [1157, 1277, 1397]
        accounts = self.data["accounts"]
        for row in range(3):
            for column, account_index in enumerate((row, row + 3)):
                account = accounts[account_index]
                x = 50 if column == 0 else 587
                marker_x = 398 if column == 0 else 902
                status_x = 418 if column == 0 else 922
                status = account["status"]
                self.text(
                    (x, name_baselines[row]),
                    account["name"],
                    28,
                    underline=status == "SIGN-IN",
                )
                self.status_marker(marker_x, name_baselines[row] - 9, status)
                self.text(
                    (status_x, name_baselines[row]),
                    status,
                    21,
                    underline=status == "SIGN-IN",
                )
                self.text(
                    (x, detail_baselines[row]),
                    f"{account['running']} RUNNING . {account['queued']} QUEUED",
                    20,
                    spacing=1.1,
                )
            self.rule((50, separators[row], 1022, separators[row]), soft=True)


def load_data(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise DashboardError(f"cannot read {path}: {exc}") from exc
    return validate(data)


def deploy(output: Path, host: str, remote_image: str, remote_render: str) -> None:
    if not shutil.which("scp") or not shutil.which("ssh"):
        raise DashboardError("ssh and scp must be available for --deploy")
    subprocess.run(
        ["scp", str(output), f"{host}:{remote_image}"],
        check=True,
    )
    remote_command = (
        f"chmod 644 {shlex.quote(remote_image)} && {shlex.quote(remote_render)}"
    )
    subprocess.run(["ssh", host, remote_command], check=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path, help="dashboard JSON file")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("panel-base.png"),
        help="output grayscale PNG (default: panel-base.png)",
    )
    parser.add_argument(
        "--header-mode",
        choices=("blank", "data", "now"),
        default="blank",
        help="blank for native Kindle overlay, data for JSON values, now for local time",
    )
    parser.add_argument(
        "--deploy",
        metavar="SSH_HOST",
        help="copy the output to a Kindle and refresh it, e.g. kindle",
    )
    parser.add_argument("--remote-image", default=DEFAULT_REMOTE_IMAGE)
    parser.add_argument("--remote-render", default=DEFAULT_REMOTE_RENDER)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data = load_data(args.data)
        image = Renderer(data, args.header_mode).render()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        image.save(args.output, format="PNG", optimize=True)
        print(f"rendered={args.output.resolve()}")
        print(f"size={image.width}x{image.height}")
        print(f"mode={image.mode}")
        if args.deploy:
            deploy(args.output, args.deploy, args.remote_image, args.remote_render)
            print(f"deployed={args.deploy}:{args.remote_image}")
        return 0
    except (DashboardError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
