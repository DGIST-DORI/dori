#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

import yaml


def default_document() -> dict[str, Any]:
    return {
        "map": "isaac_map",
        "frame_id": "map",
        "points": {},
    }


def load_points(path: Path) -> dict[str, Any]:
    if not path.exists():
        return default_document()

    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    doc = default_document()
    doc.update({k: v for k, v in data.items() if k != "points"})
    doc["points"] = data.get("points", {}) or {}
    return doc


def save_points(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=True)


def parse_tags(values: list[str]) -> dict[str, str]:
    tags: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"invalid tag '{value}', expected key=value")
        key, raw = value.split("=", 1)
        key = key.strip()
        raw = raw.strip()
        if not key:
            raise ValueError(f"invalid tag '{value}', key is empty")
        tags[key] = raw
    return tags


def quaternion_to_yaw(quaternion: Any) -> float:
    siny_cosp = 2.0 * (
        float(quaternion.w) * float(quaternion.z) + float(quaternion.x) * float(quaternion.y)
    )
    cosy_cosp = 1.0 - 2.0 * (
        float(quaternion.y) * float(quaternion.y) + float(quaternion.z) * float(quaternion.z)
    )
    return math.atan2(siny_cosp, cosy_cosp)


def cmd_list(args: argparse.Namespace) -> int:
    data = load_points(args.file)
    points = data["points"]
    if not points:
        print("No semantic points stored.")
        return 0

    print(f"Semantic points in {args.file}:")
    for name in sorted(points):
        point = points[name]
        pose = point.get("pose", {})
        tags = point.get("tags", {})
        print(
            f"- {name}: x={pose.get('x', 0.0):.3f}, y={pose.get('y', 0.0):.3f}, "
            f"yaw={pose.get('yaw', 0.0):.3f}, tags={tags}"
        )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    data = load_points(args.file)
    point = data["points"].get(args.name)
    if point is None:
        raise SystemExit(f"semantic point '{args.name}' not found in {args.file}")

    print(yaml.safe_dump({args.name: point}, sort_keys=False, allow_unicode=True).strip())
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    data = load_points(args.file)
    tags = parse_tags(args.tag or [])
    point = {
        "frame_id": args.frame_id or data.get("frame_id", "map"),
        "pose": {
            "x": float(args.x),
            "y": float(args.y),
            "yaw": float(args.yaw),
        },
        "tags": tags,
    }
    if args.description:
        point["description"] = args.description

    data["points"][args.name] = point
    save_points(args.file, data)
    print(f"Saved semantic point '{args.name}' to {args.file}")
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    data = load_points(args.file)
    removed = data["points"].pop(args.name, None)
    if removed is None:
        raise SystemExit(f"semantic point '{args.name}' not found in {args.file}")

    save_points(args.file, data)
    print(f"Deleted semantic point '{args.name}' from {args.file}")
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    import rclpy
    from geometry_msgs.msg import PoseWithCovarianceStamped
    from rclpy.node import Node

    class PoseCaptureNode(Node):
        def __init__(self, topic_name: str) -> None:
            super().__init__("semantic_point_capture")
            self.message: PoseWithCovarianceStamped | None = None
            self.subscription = self.create_subscription(
                PoseWithCovarianceStamped,
                topic_name,
                self._on_message,
                10,
            )

        def _on_message(self, message: PoseWithCovarianceStamped) -> None:
            self.message = message

    rclpy.init()
    node = PoseCaptureNode(args.topic)
    deadline = node.get_clock().now().nanoseconds + int(args.timeout * 1e9)

    try:
        while rclpy.ok() and node.message is None:
            rclpy.spin_once(node, timeout_sec=0.2)
            if node.get_clock().now().nanoseconds > deadline:
                raise SystemExit(
                    f"timed out waiting for {args.topic}; make sure localization is running"
                )

        assert node.message is not None
        pose_msg = node.message.pose.pose
        x = float(pose_msg.position.x)
        y = float(pose_msg.position.y)
        yaw = quaternion_to_yaw(pose_msg.orientation)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

    data = load_points(args.file)
    tags = parse_tags(args.tag or [])
    point = {
        "frame_id": args.frame_id or node.message.header.frame_id or data.get("frame_id", "map"),
        "pose": {
            "x": x,
            "y": y,
            "yaw": yaw,
        },
        "tags": tags,
    }
    if args.description:
        point["description"] = args.description

    data["points"][args.name] = point
    save_points(args.file, data)
    print(
        f"Captured semantic point '{args.name}' from {args.topic}: "
        f"x={x:.3f}, y={y:.3f}, yaw={yaw:.3f}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    root_dir = Path(__file__).resolve().parents[1]
    default_file = root_dir / "maps" / "isaac_map.semantic.yaml"

    parser = argparse.ArgumentParser(
        description="Manage semantic waypoint metadata stored next to the saved occupancy map."
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=default_file,
        help=f"Semantic points YAML file (default: {default_file})",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List all semantic points")
    list_parser.set_defaults(func=cmd_list)

    show_parser = subparsers.add_parser("show", help="Show one semantic point")
    show_parser.add_argument("name")
    show_parser.set_defaults(func=cmd_show)

    add_parser = subparsers.add_parser("add", help="Add or update a semantic point")
    add_parser.add_argument("name")
    add_parser.add_argument("--x", required=True, type=float)
    add_parser.add_argument("--y", required=True, type=float)
    add_parser.add_argument("--yaw", required=True, type=float)
    add_parser.add_argument("--frame-id", default="")
    add_parser.add_argument("--description", default="")
    add_parser.add_argument(
        "--tag",
        action="append",
        help="Semantic metadata as key=value. Repeat for multiple tags.",
    )
    add_parser.set_defaults(func=cmd_add)

    delete_parser = subparsers.add_parser("delete", help="Delete a semantic point")
    delete_parser.add_argument("name")
    delete_parser.set_defaults(func=cmd_delete)

    capture_parser = subparsers.add_parser(
        "capture",
        help="Capture the current localized pose from a ROS topic and save it as a semantic point",
    )
    capture_parser.add_argument("name")
    capture_parser.add_argument("--topic", default="/amcl_pose")
    capture_parser.add_argument("--timeout", default=5.0, type=float)
    capture_parser.add_argument("--frame-id", default="")
    capture_parser.add_argument("--description", default="")
    capture_parser.add_argument(
        "--tag",
        action="append",
        help="Semantic metadata as key=value. Repeat for multiple tags.",
    )
    capture_parser.set_defaults(func=cmd_capture)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
