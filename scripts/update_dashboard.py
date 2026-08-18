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
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1072
HEIGHT = 1448
LANDSCAPE_WIDTH = HEIGHT
LANDSCAPE_HEIGHT = WIDTH
ORIENTATIONS = ("portrait", "right")
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
    "calendar": [
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/System/Library/Fonts/STHeiti Medium.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
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
    def __init__(
        self,
        data: dict[str, Any],
        header_mode: str,
        agenda: list[dict[str, Any]] | None = None,
    ) -> None:
        self.data = data
        self.header_mode = header_mode
        self.agenda_data = agenda
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

    def clipped_text(
        self,
        xy: tuple[float, float],
        value: Any,
        size: int,
        max_width: float,
        family: str = "calendar",
        **kwargs: Any,
    ) -> None:
        rendered = str(value)
        font = self.font(family, size)
        if self.draw.textlength(rendered, font=font) > max_width:
            suffix = "…"
            while rendered and self.draw.textlength(rendered + suffix, font=font) > max_width:
                rendered = rendered[:-1]
            rendered = rendered.rstrip() + suffix
        self.text(xy, rendered, size, family, **kwargs)

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

class RightLandscapeRenderer(Renderer):
    """Render a landscape dashboard for a device rotated clockwise.

    The dashboard is composed upright on a 1448x1072 logical canvas, then
    rotated counter-clockwise into the Kindle's native 1072x1448 framebuffer.
    No framebuffer rotation or stock-UI orientation change is required.
    """

    def __init__(
        self,
        data: dict[str, Any],
        header_mode: str,
        agenda: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(data, header_mode, agenda)
        self.image = Image.new("L", (LANDSCAPE_WIDTH, LANDSCAPE_HEIGHT), WHITE)
        self.draw = ImageDraw.Draw(self.image)

    def render_logical(self) -> Image.Image:
        self.draw.rectangle(
            (0, 0, LANDSCAPE_WIDTH - 1, LANDSCAPE_HEIGHT - 1), fill=WHITE
        )
        self.draw.rectangle(
            (2, 2, LANDSCAPE_WIDTH - 3, LANDSCAPE_HEIGHT - 3),
            outline=DARK,
            width=4,
        )
        self.landscape_header()
        self.landscape_capacity()
        self.landscape_nodes()
        self.landscape_accounts()
        return self.image

    def render(self) -> Image.Image:
        logical = self.render_logical()
        return logical.transpose(Image.Transpose.ROTATE_90)

    def landscape_header(self) -> None:
        cluster = self.data["cluster"]
        self.draw.rectangle((52, 47, 98, 91), outline=DARK, width=6)
        self.draw.rectangle((66, 60, 84, 78), fill=DARK)
        self.text((120, 69), cluster["name"], 32, "sans_bold", spacing=2.2)
        self.text((121, 96), cluster["subtitle"], 17, spacing=1.8)

        if self.header_mode != "blank":
            header = self.data["header"]
            if self.header_mode == "now":
                current = datetime.now()
                time_value = current.strftime("%H:%M")
                date_value = current.strftime("%a . %b %d").upper().replace(" 0", " ")
            else:
                time_value = header["time"]
                date_value = header["date"]
            self.text((1125, 76), time_value, 45, "sans_bold", "ms")
            self.text((1125, 105), date_value, 18, anchor="ms", spacing=1.8)
            self.draw.rectangle((1256, 54, 1309, 78), outline=DARK, width=5)
            self.draw.rectangle((1309, 60, 1316, 72), fill=DARK)
            self.draw.rectangle((1262, 60, 1302, 72), fill=DARK)
            self.text((1331, 70), f"{header['battery']}%", 29, "sans_bold")
            self.text((1331, 98), "BATTERY", 16, spacing=1.5)
        else:
            self.text((1396, 77), "HPC STATUS BOARD", 17, "sans_bold", "rs", spacing=1.5)
            self.text((1396, 101), "AUTO-UPDATED", 14, anchor="rs", spacing=1.2)
        self.rule((52, 128, 1396, 128), width=4)

    def landscape_capacity(self) -> None:
        cap = self.data["capacity"]
        self.text((52, 174), "LIVE CAPACITY", 20, spacing=1.5)
        if cap["all_systems_online"]:
            self.draw.ellipse((254, 159, 269, 174), outline=DARK, width=4)
            status = "ALL SYSTEMS ONLINE"
        else:
            self.draw.ellipse((254, 159, 269, 174), fill=DARK)
            status = "ATTENTION REQUIRED"
        self.text((280, 174), status, 18, spacing=1.2)

        self.text((56, 322), cap["gpus_free"], 132, "serif")
        self.text((337, 330), f"/ {cap['gpus_total']}", 55, "serif")
        self.text((58, 382), "GPUs FREE", 32, "sans_bold", spacing=1.2)
        percent = cap["gpus_free"] / cap["gpus_total"] * 100
        self.text((488, 382), f"{percent:.1f}% AVAILABLE", 18, anchor="rs", spacing=1.3)

        self.rule((528, 158, 528, 400), width=4)
        stats = (
            (566, cap["cpu_cores_free"], "CPU CORES FREE"),
            (854, cap["jobs_running"], "JOBS RUNNING"),
            (1125, cap["jobs_queued"], "JOBS QUEUED"),
        )
        for x, number, label in stats:
            self.text((x, 297), number, 86, "serif")
            self.text((x, 337), label, 19, "sans_bold", spacing=1.1)
        self.rule((820, 202, 820, 360), soft=True)
        self.rule((1091, 202, 1091, 360), soft=True)

        used = cap["gpus_total"] - cap["gpus_free"]
        self.text((52, 432), "GPU CAPACITY", 19, "sans_bold", spacing=1.3)
        self.text(
            (1396, 432),
            f"USED {used}    FREE {cap['gpus_free']}",
            18,
            anchor="rs",
            spacing=1.0,
        )
        self.blocks(52, 449, 1344, 29, cap["gpus_total"], used, gap=3)
        self.rule((52, 505, 1396, 505), width=6)

    def landscape_nodes(self) -> None:
        self.text((52, 559), "NODE AVAILABILITY", 30, spacing=2.0)
        self.draw.rectangle((602, 542, 615, 556), fill=DARK)
        self.text((624, 559), "USED", 15)
        self.draw.rectangle((690, 542, 703, 556), fill=WHITE, outline=DARK, width=2)
        self.text((712, 559), "FREE", 15)
        self.rule((52, 580, 780, 580), soft=True)

        baselines = (628, 725, 822, 919)
        for index, (node, baseline) in enumerate(zip(self.data["nodes"], baselines)):
            self.text((52, baseline), node["name"], 25, "sans_bold")
            self.text((52, baseline + 24), node["state"], 16, spacing=1.3)
            used = node["total"] - node["free"]
            self.blocks(235, baseline - 18, 375, 24, node["total"], used, gap=6)
            self.text((706, baseline + 9), node["free"], 39, "serif", anchor="rs")
            self.text((716, baseline + 7), f"/ {node['total']} FREE", 16)
            if index < 3:
                self.rule((52, baseline + 48, 780, baseline + 48), soft=True)

    def landscape_accounts(self) -> None:
        left = 820
        self.rule((800, 532, 800, 1022), width=4)
        self.text((left, 559), "ACCOUNT ACTIVITY", 30, spacing=2.0)
        self.text((1396, 558), "6 ACCOUNTS", 17, anchor="rs", spacing=1.4)
        self.rule((left, 580, 1396, 580), soft=True)

        baselines = (625, 694, 763, 832, 901, 970)
        for index, (account, baseline) in enumerate(zip(self.data["accounts"], baselines)):
            status = account["status"]
            self.text(
                (left, baseline),
                account["name"],
                23,
                "sans_bold",
                underline=status == "SIGN-IN",
            )
            self.status_marker(1111, baseline - 8, status)
            self.text(
                (1132, baseline),
                status,
                18,
                underline=status == "SIGN-IN",
            )
            self.text(
                (1396, baseline),
                f"{account['running']} RUN  ·  {account['queued']} QUEUE",
                17,
                anchor="rs",
                spacing=0.7,
            )
            if index < 5:
                self.rule((left, baseline + 25, 1396, baseline + 25), soft=True)

class CalendarRenderer(Renderer):
    """Render an Apple-inspired standalone six-week month grid."""

    LOGICAL_WIDTH = WIDTH
    LOGICAL_HEIGHT = HEIGHT
    MARGIN = 42
    HEADER_BOTTOM = 164
    WEEKDAY_BOTTOM = 224
    GRID_BOTTOM = 1406
    TITLE_SIZE = 51
    WEEKDAY_SIZE = 20
    DATE_SIZE = 22
    EVENT_SIZE = 14
    EVENT_HEIGHT = 28
    EVENT_GAP = 7
    EVENTS_PER_DAY = 4

    def __init__(
        self,
        data: dict[str, Any],
        header_mode: str,
        agenda: list[dict[str, Any]],
        calendar_date: str,
    ) -> None:
        super().__init__(data, header_mode, agenda)
        try:
            self.day = datetime.fromisoformat(calendar_date).date()
        except ValueError as exc:
            raise DashboardError("calendar_date must use ISO format") from exc
        self.month_start = self.day.replace(day=1)
        self.grid_start = self.month_start - timedelta(
            days=(self.month_start.weekday() + 1) % 7
        )
        self.image = Image.new(
            "L", (self.LOGICAL_WIDTH, self.LOGICAL_HEIGHT), WHITE
        )
        self.draw = ImageDraw.Draw(self.image)
        self.events_by_day = self._events_by_day()

    def _events_by_day(self) -> dict[date, list[dict[str, Any]]]:
        grouped: dict[date, list[dict[str, Any]]] = {}
        for event in self.agenda_data or []:
            try:
                event_day = date.fromisoformat(str(event["date"]))
                title = str(event["title"]).strip()
                event_time = str(event.get("time", "")).strip()
            except (KeyError, TypeError, ValueError) as exc:
                raise DashboardError("calendar event is invalid") from exc
            if not title or len(event_time) > 5:
                raise DashboardError("calendar event is invalid")
            grouped.setdefault(event_day, []).append(
                {
                    "title": title,
                    "time": event_time,
                    "all_day": bool(event.get("all_day")),
                }
            )
        return grouped

    def render(self) -> Image.Image:
        self._render_logical()
        return self.image

    def _render_logical(self) -> None:
        width, height = self.LOGICAL_WIDTH, self.LOGICAL_HEIGHT
        self.draw.rectangle((0, 0, width - 1, height - 1), fill=WHITE)
        self.draw.rectangle((2, 2, width - 3, height - 3), outline=DARK, width=4)
        self._month_header()
        self._month_grid()

    def _month_header(self) -> None:
        left = self.MARGIN
        width = self.LOGICAL_WIDTH
        month_title = f"{self.day.year}年 {self.day.month}月"
        self.text((left, 82), month_title, self.TITLE_SIZE, "calendar")
        self.text((left + 2, 118), "APPLE CALENDAR · 本月", 16, "calendar", spacing=1.0)

        segment_width = 184
        segment_left = (width - segment_width) // 2
        segment_top = 48
        segment_bottom = 91
        self.draw.rounded_rectangle(
            (segment_left, segment_top, segment_left + segment_width, segment_bottom),
            radius=9,
            fill=235,
            outline=190,
            width=2,
        )
        labels = ("日", "周", "月", "年")
        segment = segment_width / 4
        active_left = int(segment_left + 2 * segment)
        self.draw.rounded_rectangle(
            (active_left, segment_top + 2, int(active_left + segment), segment_bottom - 2),
            radius=7,
            fill=76,
        )
        for index, label in enumerate(labels):
            self.text(
                (segment_left + segment * (index + 0.5), 70),
                label,
                17,
                "calendar",
                "mm",
                fill=WHITE if index == 2 else DARK,
            )
        self.text((width - self.MARGIN, 78), "自动更新", 17, "calendar", "rs")
        self.text((width - self.MARGIN, 111), "UTC+8", 14, "sans_bold", "rs", fill=MID)
        self.rule((left, self.HEADER_BOTTOM, width - left, self.HEADER_BOTTOM), width=3)

    def _month_grid(self) -> None:
        left = self.MARGIN
        right = self.LOGICAL_WIDTH - self.MARGIN
        grid_top = self.WEEKDAY_BOTTOM
        col_width = (right - left) / 7
        row_height = (self.GRID_BOTTOM - grid_top) / 6
        weekdays = ("周日", "周一", "周二", "周三", "周四", "周五", "周六")
        for column, label in enumerate(weekdays):
            center = left + col_width * (column + 0.5)
            self.text(
                (center, self.HEADER_BOTTOM + 34),
                label,
                self.WEEKDAY_SIZE,
                "calendar",
                "mm",
                fill=MID if column in (0, 6) else DARK,
            )
        for row in range(6):
            for column in range(7):
                cell_left = int(round(left + col_width * column))
                cell_right = int(round(left + col_width * (column + 1)))
                cell_top = int(round(grid_top + row_height * row))
                cell_bottom = int(round(grid_top + row_height * (row + 1)))
                cell_day = self.grid_start + timedelta(days=row * 7 + column)
                if cell_day.month != self.day.month:
                    self.draw.rectangle(
                        (cell_left + 1, cell_top + 1, cell_right - 1, cell_bottom - 1),
                        fill=246,
                    )
                self._day_cell(
                    cell_day,
                    cell_left,
                    cell_top,
                    cell_right,
                    cell_bottom,
                    column,
                )
        for column in range(8):
            x = int(round(left + col_width * column))
            self.rule((x, grid_top, x, self.GRID_BOTTOM), width=2, soft=True)
        for row in range(7):
            y = int(round(grid_top + row_height * row))
            self.rule((left, y, right, y), width=2, soft=True)

    def _day_cell(
        self,
        cell_day: date,
        left: int,
        top: int,
        right: int,
        bottom: int,
        column: int,
    ) -> None:
        date_label = f"{cell_day.month}月{cell_day.day}日" if cell_day.day == 1 else f"{cell_day.day}日"
        date_fill = MID if cell_day.month != self.day.month or column in (0, 6) else DARK
        date_x = right - 11
        date_y = top + 29
        if cell_day == self.day:
            radius = 20
            center_x = right - 28
            center_y = top + 25
            self.draw.ellipse(
                (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
                fill=DARK,
            )
            self.text(
                (center_x, center_y),
                str(cell_day.day),
                self.DATE_SIZE,
                "sans_bold",
                "mm",
                fill=WHITE,
            )
        else:
            self.text(
                (date_x, date_y),
                date_label,
                self.DATE_SIZE,
                "calendar",
                "rs",
                fill=date_fill,
            )

        events = self.events_by_day.get(cell_day, [])
        bar_top = top + 50
        max_width = right - left - 14
        for index, event in enumerate(events[: self.EVENTS_PER_DAY]):
            y = bar_top + index * (self.EVENT_HEIGHT + self.EVENT_GAP)
            if y + self.EVENT_HEIGHT >= bottom - 5:
                break
            all_day = event["all_day"]
            fill = 55 if all_day else 218
            text_fill = WHITE if all_day else DARK
            self.draw.rounded_rectangle(
                (left + 5, y, right - 5, y + self.EVENT_HEIGHT),
                radius=7,
                fill=fill,
                outline=fill if all_day else 175,
                width=1,
            )
            prefix = "" if all_day or not event["time"] else f"{event['time']} "
            self.clipped_text(
                (left + 11, y + self.EVENT_HEIGHT - 7),
                prefix + event["title"],
                self.EVENT_SIZE,
                max_width - 12,
                family="calendar",
                fill=text_fill,
            )
        hidden = len(events) - min(len(events), self.EVENTS_PER_DAY)
        if hidden > 0:
            self.text(
                (right - 9, bottom - 9),
                f"+{hidden}",
                14,
                "sans_bold",
                "rs",
                fill=MID,
            )


class RightCalendarRenderer(CalendarRenderer):
    """Pre-rotate the Apple month view for clockwise physical placement."""

    LOGICAL_WIDTH = LANDSCAPE_WIDTH
    LOGICAL_HEIGHT = LANDSCAPE_HEIGHT
    MARGIN = 44
    HEADER_BOTTOM = 128
    WEEKDAY_BOTTOM = 182
    GRID_BOTTOM = 1024
    TITLE_SIZE = 45
    WEEKDAY_SIZE = 18
    DATE_SIZE = 19
    EVENT_SIZE = 14
    EVENT_HEIGHT = 26
    EVENT_GAP = 5
    EVENTS_PER_DAY = 2

    def render(self) -> Image.Image:
        self._render_logical()
        return self.image.transpose(Image.Transpose.ROTATE_90)


def render_dashboard(
    data: dict[str, Any],
    header_mode: str = "blank",
    orientation: str = "portrait",
    agenda: list[dict[str, Any]] | None = None,
    calendar_date: str | None = None,
) -> Image.Image:
    if agenda is not None:
        effective_date = calendar_date or datetime.now().date().isoformat()
        if orientation == "portrait":
            return CalendarRenderer(data, header_mode, agenda, effective_date).render()
        if orientation == "right":
            return RightCalendarRenderer(data, header_mode, agenda, effective_date).render()
        raise DashboardError(f"unsupported orientation: {orientation}")
    if orientation == "portrait":
        return Renderer(data, header_mode, agenda).render()
    if orientation == "right":
        return RightLandscapeRenderer(data, header_mode, agenda).render()
    raise DashboardError(f"unsupported orientation: {orientation}")


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
        "--orientation",
        choices=ORIENTATIONS,
        default="portrait",
        help="portrait, or right when the Kindle is physically rotated clockwise",
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
        image = render_dashboard(data, args.header_mode, args.orientation)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        image.save(args.output, format="PNG", optimize=True)
        print(f"rendered={args.output.resolve()}")
        print(f"size={image.width}x{image.height}")
        print(f"mode={image.mode}")
        print(f"orientation={args.orientation}")
        if args.deploy:
            deploy(args.output, args.deploy, args.remote_image, args.remote_render)
            print(f"deployed={args.deploy}:{args.remote_image}")
        return 0
    except (DashboardError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
