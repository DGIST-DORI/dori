#!/usr/bin/env python3

import argparse
import threading
import time

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from sensor_msgs.msg import Image


WINDOW_NAME = "FPV Viewer"
PANEL_W = 300


class FPVViewer(Node):
    def __init__(self, image_topic: str):
        super().__init__("fpv_viewer")

        self.image_topic = image_topic
        self.bridge = CvBridge()
        self.sub = self.create_subscription(Image, self.image_topic, self.on_image, 10)

        self.running = True
        self._frame_lock = threading.Lock()
        self._last_frame = None
        self._last_frame_stamp = None
        self._img_hz = 0.0
        self._last_img_time = None

        self.get_logger().info(f"Started viewer. image_topic={self.image_topic}")

    def on_image(self, msg: Image):
        try:
            cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as exc:
            self.get_logger().error(f"Image conversion failed: {exc}")
            return

        now = time.time()
        if self._last_img_time is not None:
            dt = now - self._last_img_time
            if dt > 0.0:
                inst = 1.0 / dt
                self._img_hz = 0.8 * self._img_hz + 0.2 * inst
        self._last_img_time = now

        with self._frame_lock:
            self._last_frame = cv_image
            self._last_frame_stamp = now

    def draw_ui(self, frame: np.ndarray | None) -> np.ndarray:
        if frame is None:
            frame = np.zeros((480, 640, 3), dtype=np.uint8)

        h, w = frame.shape[:2]
        panel = np.zeros((h, PANEL_W, 3), dtype=np.uint8)
        panel[:] = (20, 20, 20)

        cv2.putText(
            panel,
            "ROS2 FPV Viewer",
            (15, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.75,
            (230, 230, 230),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            panel,
            f"image <- {self.image_topic}",
            (15, 78),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (200, 200, 200),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            panel,
            "cmd_vel publish: disabled",
            (15, 104),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (120, 220, 120),
            1,
            cv2.LINE_AA,
        )

        now = time.time()
        with self._frame_lock:
            stamp = self._last_frame_stamp
        age = (now - stamp) if stamp is not None else None
        age_txt = f"{age:.2f}s" if age is not None else "N/A"
        cv2.putText(
            panel,
            f"Image Hz: {self._img_hz:.1f}",
            (15, 145),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.60,
            (230, 230, 230),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            panel,
            f"Frame age: {age_txt}",
            (15, 170),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.60,
            (230, 230, 230),
            1,
            cv2.LINE_AA,
        )

        help_lines = [
            "Viewer-only window",
            "",
            "Use this during Nav2 to watch",
            "where the robot is heading",
            "without interfering with /cmd_vel.",
            "",
            "Q or ESC: close viewer",
        ]
        y = 235
        for line in help_lines:
            cv2.putText(
                panel,
                line,
                (15, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (210, 210, 210),
                1,
                cv2.LINE_AA,
            )
            y += 26

        combined = np.hstack([frame, panel])
        return self._draw_crosshair(combined, w // 2, h // 2)

    def _draw_crosshair(self, img: np.ndarray, cx: int, cy: int) -> np.ndarray:
        cv2.line(img, (cx - 12, cy), (cx + 12, cy), (0, 255, 0), 1)
        cv2.line(img, (cx, cy - 12), (cx, cy + 12), (0, 255, 0), 1)
        return img

    def ui_loop(self):
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)

        ui_dt = 1.0 / 30.0
        last = time.time()

        while self.running and rclpy.ok():
            now = time.time()
            if now - last < ui_dt:
                time.sleep(0.001)
                continue
            last = now

            with self._frame_lock:
                frame = None if self._last_frame is None else self._last_frame.copy()

            cv2.imshow(WINDOW_NAME, self.draw_ui(frame))

            key = cv2.waitKey(1)
            if key in (27, ord("q"), ord("Q")):
                self.running = False

        try:
            cv2.destroyAllWindows()
        except Exception:
            pass

        self.get_logger().info("Viewer finished. Exiting...")

    def shutdown(self):
        self.running = False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image_topic", default="/rgb", help="Image topic (sensor_msgs/Image)")
    args = parser.parse_args()

    rclpy.init()
    node = FPVViewer(image_topic=args.image_topic)

    spin_thread = threading.Thread(target=rclpy.spin, args=(node,), daemon=True)
    spin_thread.start()

    try:
        node.ui_loop()
    except KeyboardInterrupt:
        pass
    finally:
        node.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
