#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
import warnings
from pathlib import Path
from typing import Any

warnings.filterwarnings(
    "ignore",
    message="Unable to import Axes3D.*",
    category=UserWarning,
    module="matplotlib.projections",
)

import matplotlib.pyplot as plt
import numpy as np
import yaml
from matplotlib.widgets import Button, TextBox
from PIL import Image


CSV_FIELDS = ["name", "x", "y", "yaw_deg", "frame_id"]


def load_map_yaml(map_yaml: Path) -> dict[str, Any]:
    with map_yaml.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    if not math.isclose(float(data["origin"][2]), 0.0, abs_tol=1e-10):
        raise ValueError("This editor requires map origin yaw=0; use world-coordinate CSV for a rotated map")
    image_path = Path(data["image"])
    if not image_path.is_absolute():
        image_path = (map_yaml.parent / image_path).resolve()

    return {
        "image_path": image_path,
        "resolution": float(data["resolution"]),
        "origin_x": float(data["origin"][0]),
        "origin_y": float(data["origin"][1]),
    }


def load_points(points_csv: Path) -> dict[str, dict[str, Any]]:
    if not points_csv.exists():
        return {}

    points: dict[str, dict[str, Any]] = {}
    with points_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            name = (row.get("name") or "").strip()
            if not name:
                continue
            points[name] = {
                "name": name,
                "x": float(row.get("x", 0.0)),
                "y": float(row.get("y", 0.0)),
                "yaw_deg": float(row.get("yaw_deg", 0.0)),
                "frame_id": (row.get("frame_id") or "map").strip() or "map",
            }
    return points


def save_points(points_csv: Path, points: dict[str, dict[str, Any]]) -> None:
    points_csv.parent.mkdir(parents=True, exist_ok=True)
    with points_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for name in sorted(points):
            point = points[name]
            writer.writerow(
                {
                    "name": point["name"],
                    "x": f"{point['x']:.6f}",
                    "y": f"{point['y']:.6f}",
                    "yaw_deg": f"{point['yaw_deg']:.3f}",
                    "frame_id": point["frame_id"],
                }
            )


class NamedPointsEditor:
    def __init__(self, map_yaml: Path, points_csv: Path) -> None:
        self.map_yaml = map_yaml
        self.points_csv = points_csv
        self.map_info = load_map_yaml(map_yaml)
        self.points = load_points(points_csv)
        self.pending_x: float | None = None
        self.pending_y: float | None = None

        image = np.array(Image.open(self.map_info["image_path"]).convert("L"))
        self.image = image

        resolution = self.map_info["resolution"]
        origin_x = self.map_info["origin_x"]
        origin_y = self.map_info["origin_y"]
        height, width = image.shape
        self.extent = [
            origin_x,
            origin_x + width * resolution,
            origin_y,
            origin_y + height * resolution,
        ]

        self.figure, self.axes = plt.subplots(figsize=(13, 10))
        self.figure.subplots_adjust(right=0.72)
        self.scatter = None
        self.labels: list[Any] = []
        self.pending_scatter = None

        self.axes.imshow(
            self.image,
            cmap="gray",
            origin="upper",
            extent=self.extent,
            vmin=0,
            vmax=255,
        )
        self.axes.set_title("Click a point on the map, then use the panel on the right to save it")
        self.axes.set_xlabel("map x [m]")
        self.axes.set_ylabel("map y [m]")
        self.axes.set_aspect("equal")

        self.coord_text = self.figure.text(
            0.75,
            0.88,
            "Selected point: none",
            fontsize=10,
            va="top",
        )
        self.status_text = self.figure.text(
            0.75,
            0.82,
            "Status: click on the map",
            fontsize=10,
            va="top",
        )

        name_ax = self.figure.add_axes([0.75, 0.70, 0.20, 0.05])
        yaw_ax = self.figure.add_axes([0.75, 0.61, 0.20, 0.05])
        frame_ax = self.figure.add_axes([0.75, 0.52, 0.20, 0.05])
        save_ax = self.figure.add_axes([0.75, 0.42, 0.20, 0.06])
        help_ax = self.figure.add_axes([0.75, 0.18, 0.22, 0.18])
        help_ax.axis("off")
        help_ax.text(
            0.0,
            1.0,
            "Usage:\n"
            "1. Left-click map\n"
            "2. Type point name\n"
            "3. Optional yaw in degrees\n"
            "4. Click Save point\n\n"
            "Existing names are overwritten.",
            va="top",
            fontsize=9,
        )

        self.name_box = TextBox(name_ax, "Name ", initial="")
        self.yaw_box = TextBox(yaw_ax, "Yaw ", initial="0")
        self.frame_box = TextBox(frame_ax, "Frame ", initial="map")
        self.save_button = Button(save_ax, "Save point")
        self.save_button.on_clicked(self.on_save)

        self.redraw_points()

        self.figure.canvas.mpl_connect("button_press_event", self.on_click)

    def redraw_points(self) -> None:
        if self.scatter is not None:
            self.scatter.remove()
            self.scatter = None
        for label in self.labels:
            label.remove()
        self.labels.clear()

        if not self.points:
            self.figure.canvas.draw_idle()
            return

        xs = [point["x"] for point in self.points.values()]
        ys = [point["y"] for point in self.points.values()]
        self.scatter = self.axes.scatter(xs, ys, c="red", s=40)

        for point in self.points.values():
            label = self.axes.text(
                point["x"] + 0.05,
                point["y"] + 0.05,
                point["name"],
                color="red",
                fontsize=9,
                bbox={"facecolor": "white", "alpha": 0.7, "edgecolor": "none"},
            )
            self.labels.append(label)

        self.figure.canvas.draw_idle()

    def redraw_pending_point(self) -> None:
        if self.pending_scatter is not None:
            self.pending_scatter.remove()
            self.pending_scatter = None

        if self.pending_x is not None and self.pending_y is not None:
            self.pending_scatter = self.axes.scatter(
                [self.pending_x],
                [self.pending_y],
                c="cyan",
                s=70,
                marker="x",
                linewidths=2.0,
            )

        self.figure.canvas.draw_idle()

    def on_click(self, event: Any) -> None:
        if event.inaxes != self.axes or event.xdata is None or event.ydata is None:
            return

        self.pending_x = float(event.xdata)
        self.pending_y = float(event.ydata)
        self.coord_text.set_text(
            f"Selected point: x={self.pending_x:.3f}, y={self.pending_y:.3f}"
        )
        self.status_text.set_text("Status: enter a name, then click Save point")
        self.redraw_pending_point()

    def on_save(self, _event: Any) -> None:
        if self.pending_x is None or self.pending_y is None:
            self.status_text.set_text("Status: click on the map first")
            self.figure.canvas.draw_idle()
            return

        name = self.name_box.text.strip()
        if not name:
            self.status_text.set_text("Status: point name is required")
            self.figure.canvas.draw_idle()
            return

        yaw_text = self.yaw_box.text.strip()
        frame_id = self.frame_box.text.strip() or "map"

        try:
            yaw_deg = float(yaw_text) if yaw_text else 0.0
        except ValueError:
            self.status_text.set_text("Status: yaw must be a number")
            self.figure.canvas.draw_idle()
            return

        self.points[name] = {
            "name": name,
            "x": self.pending_x,
            "y": self.pending_y,
            "yaw_deg": yaw_deg,
            "frame_id": frame_id,
        }
        save_points(self.points_csv, self.points)
        self.status_text.set_text(f"Status: saved '{name}'")
        self.name_box.set_val("")
        self.redraw_points()

    def run(self) -> None:
        print(f"Map YAML: {self.map_yaml}")
        print(f"Points CSV: {self.points_csv}")
        print("Left-click on the map, then use the right-side panel to save the point.")
        plt.show()


def build_parser() -> argparse.ArgumentParser:
    root_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Open a saved occupancy map and record named goal points.")
    parser.add_argument(
        "--map_yaml",
        type=Path,
        default=root_dir / "maps" / "test_loop.yaml",
        help="Saved occupancy map YAML file",
    )
    parser.add_argument(
        "--points_csv",
        type=Path,
        default=root_dir / "maps" / "test_loop.points.csv",
        help="CSV file used to store named points",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    editor = NamedPointsEditor(args.map_yaml.resolve(), args.points_csv.resolve())
    editor.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
