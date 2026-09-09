#!/usr/bin/env python3

import argparse
import threading
import time
from dataclasses import dataclass

import rclpy
from rclpy.node import Node

from geometry_msgs.msg import Twist
from sensor_msgs.msg import Image
from cv_bridge import CvBridge

import cv2
import numpy as np


# ----------------------------
# Tunables
# ----------------------------
LINEAR_STEP = 0.2
ANGULAR_STEP = 0.05
MAX_LINEAR = 2.0
MAX_ANGULAR = 1.0

PUBLISH_HZ = 10.0  # cmd_vel publish rate

WINDOW_NAME = "FPV + Control Board"
PANEL_W = 430  # right-side panel width


@dataclass
class VelState:
    linear: float = 0.0
    angular: float = 0.0

    def clamp(self):
        self.linear = max(-MAX_LINEAR, min(MAX_LINEAR, self.linear))
        self.angular = max(-MAX_ANGULAR, min(MAX_ANGULAR, self.angular))

    def stop(self):
        self.linear = 0.0
        self.angular = 0.0


class FPVControlBoard(Node):
    def __init__(self, image_topic: str, cmd_vel_topic: str):
        super().__init__("fpv_control_board")

        self.image_topic = image_topic
        self.cmd_vel_topic = cmd_vel_topic

        # ROS interfaces
        self.pub = self.create_publisher(Twist, self.cmd_vel_topic, 10)
        self.bridge = CvBridge()
        self.sub = self.create_subscription(Image, self.image_topic, self.on_image, 10)

        # State
        self.vel = VelState()
        self.running = True

        # Last frame (thread-safe)
        self._frame_lock = threading.Lock()
        self._last_frame = None  # np.ndarray (BGR)
        self._last_frame_stamp = None
        self._img_hz = 0.0
        self._last_img_time = None

        # UI state
        self._mouse_down = False
        self._clicked_button = None

        # Timer: publish cmd_vel
        period = 1.0 / max(1.0, PUBLISH_HZ)
        self.timer = self.create_timer(period, self.publish_cmd)

        self.get_logger().info(f"Started. image_topic={self.image_topic}, cmd_vel_topic={self.cmd_vel_topic}")

    # ----------------------------
    # ROS callbacks
    # ----------------------------
    def on_image(self, msg: Image):
        try:
            cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as e:
            self.get_logger().error(f"Image conversion failed: {e}")
            return

        now = time.time()
        if self._last_img_time is not None:
            dt = now - self._last_img_time
            if dt > 0:
                # simple EMA-ish smoothing
                inst = 1.0 / dt
                self._img_hz = 0.8 * self._img_hz + 0.2 * inst
        self._last_img_time = now

        with self._frame_lock:
            self._last_frame = cv_image
            self._last_frame_stamp = now

    def publish_cmd(self):
        msg = Twist()
        msg.linear.x = float(self.vel.linear)
        msg.angular.z = float(self.vel.angular)
        self.pub.publish(msg)

    # ----------------------------
    # UI / Control helpers
    # ----------------------------
    def apply_key(self, key: int):
        """
        OpenCV key code handling.
        cv2.waitKey returns int; for arrows it depends on platform.
        We handle:
          - ASCII keys: wasd, space, q, etc.
          - Special keys: try multiple common codes for arrows.
        """
        # Normalize: OpenCV returns 0..255 for ASCII; -1 for no key
        if key == -1:
            return

        # ESC
        if key == 27:
            self.running = False
            return

        # Space
        if key == ord(" "):
            self.vel.stop()
            return

        # Quit
        if key in (ord("q"), ord("Q")):
            self.running = False
            return

        # WASD
        if key in (ord("w"), ord("W")):
            self.vel.linear += LINEAR_STEP
        elif key in (ord("s"), ord("S")):
            self.vel.linear -= LINEAR_STEP
        elif key in (ord("a"), ord("A")):
            self.vel.angular += ANGULAR_STEP
        elif key in (ord("d"), ord("D")):
            self.vel.angular -= ANGULAR_STEP

        # Zero helpers
        elif key in (ord("x"), ord("X")):
            self.vel.angular = 0.0
        elif key in (ord("z"), ord("Z")):
            self.vel.linear = 0.0

        # Arrow keys (OpenCV varies by OS/backend)
        # Common patterns:
        #  - Linux GTK: 82/84/81/83 sometimes, or 2490368 etc in some setups
        ARROW_UP = {82, 2490368}
        ARROW_DOWN = {84, 2621440}
        ARROW_LEFT = {81, 2424832}
        ARROW_RIGHT = {83, 2555904}

        if key in ARROW_UP:
            self.vel.linear += LINEAR_STEP
        elif key in ARROW_DOWN:
            self.vel.linear -= LINEAR_STEP
        elif key in ARROW_LEFT:
            self.vel.angular += ANGULAR_STEP
        elif key in ARROW_RIGHT:
            self.vel.angular -= ANGULAR_STEP

        self.vel.clamp()

    def draw_ui(self, frame: np.ndarray) -> np.ndarray:
        """
        Creates a combined image: [FPV | Control Panel]
        """
        if frame is None:
            # fallback blank canvas if no frame received yet
            frame = np.zeros((480, 640, 3), dtype=np.uint8)

        h, w = frame.shape[:2]
        panel = np.zeros((h, PANEL_W, 3), dtype=np.uint8)

        # Panel background
        panel[:] = (20, 20, 20)

        # Title
        cv2.putText(panel, "ROS2 FPV Control Board", (15, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (230, 230, 230), 2, cv2.LINE_AA)

        # Status
        v = self.vel
        cv2.putText(panel, f"cmd_vel -> {self.cmd_vel_topic}", (15, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1, cv2.LINE_AA)
        cv2.putText(panel, f"image <- {self.image_topic}", (15, 92),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1, cv2.LINE_AA)

        # Image fps / age
        now = time.time()
        with self._frame_lock:
            stamp = self._last_frame_stamp
        age = (now - stamp) if stamp is not None else None
        age_txt = f"{age:.2f}s" if age is not None else "N/A"
        cv2.putText(panel, f"Image Hz: {self._img_hz:.1f}  Age: {age_txt}", (15, 118),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1, cv2.LINE_AA)

        # Velocity bars
        cv2.putText(panel, "Velocity", (15, 160),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (230, 230, 230), 2, cv2.LINE_AA)

        # Linear bar
        self._draw_bar(panel, 15, 185, PANEL_W - 30, 18,
                       value=v.linear, vmin=-MAX_LINEAR, vmax=MAX_LINEAR,
                       label=f"Linear x: {v.linear:+.2f} m/s")

        # Angular bar
        self._draw_bar(panel, 15, 220, PANEL_W - 30, 18,
                       value=v.angular, vmin=-MAX_ANGULAR, vmax=MAX_ANGULAR,
                       label=f"Angular z: {v.angular:+.2f} rad/s")

        # Buttons (mouse clickable)
        # Layout
        y0 = 270
        btn_w = (PANEL_W - 45) // 2
        btn_h = 45

        # Row 1: Forward / Stop
        self._draw_button(panel, 15, y0, btn_w, btn_h, "Forward (+)", "FWD")
        self._draw_button(panel, 30 + btn_w, y0, btn_w, btn_h, "Stop", "STOP")

        # Row 2: Left / Right
        y1 = y0 + 60
        self._draw_button(panel, 15, y1, btn_w, btn_h, "Turn Left (+)", "LEFT")
        self._draw_button(panel, 30 + btn_w, y1, btn_w, btn_h, "Turn Right (-)", "RIGHT")

        # Row 3: Backward / Zero Ang / Zero Lin
        y2 = y1 + 60
        self._draw_button(panel, 15, y2, btn_w, btn_h, "Backward (-)", "BACK")
        self._draw_button(panel, 30 + btn_w, y2, btn_w, btn_h, "Zero Angular", "ZANG")

        y3 = y2 + 60
        self._draw_button(panel, 15, y3, btn_w, btn_h, "Zero Linear", "ZLIN")
        self._draw_button(panel, 30 + btn_w, y3, btn_w, btn_h, "Quit", "QUIT")

        # Help text
        y_help = y3 + 75
        help_lines = [
            "Keys:",
            "  W/S : linear +/-",
            "  A/D : angular +/-",
            "  SPACE: STOP   Q/ESC: Quit",
            "  Z: zero linear   X: zero angular",
        ]
        y = y_help
        for line in help_lines:
            cv2.putText(panel, line, (15, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.52, (210, 210, 210), 1, cv2.LINE_AA)
            y += 22

        # Combine
        combined = np.hstack([frame, panel])

        # Overlay crosshair on FPV
        combined = self._draw_crosshair(combined, w // 2, h // 2)

        return combined

    def _draw_crosshair(self, img, cx, cy):
        # cx, cy are FPV center coordinates (left side of combined)
        cv2.line(img, (cx - 12, cy), (cx + 12, cy), (0, 255, 0), 1)
        cv2.line(img, (cx, cy - 12), (cx, cy + 12), (0, 255, 0), 1)
        return img

    def _draw_bar(self, panel, x, y, w, h, value, vmin, vmax, label):
        # Bar outline
        cv2.rectangle(panel, (x, y), (x + w, y + h), (140, 140, 140), 1)

        # Midline
        mid = x + w // 2
        cv2.line(panel, (mid, y), (mid, y + h), (80, 80, 80), 1)

        # Fill based on value
        # Map value -> [-1, 1]
        norm = 0.0
        if vmax > vmin:
            norm = (value - 0.0) / (vmax - 0.0)  # relative to zero
        # Better: split negative/positive fill
        if value >= 0:
            fill_w = int((value / max(1e-9, vmax)) * (w // 2))
            cv2.rectangle(panel, (mid, y + 1), (mid + fill_w, y + h - 1), (60, 180, 60), -1)
        else:
            fill_w = int(((-value) / max(1e-9, -vmin)) * (w // 2))
            cv2.rectangle(panel, (mid - fill_w, y + 1), (mid, y + h - 1), (60, 60, 180), -1)

        cv2.putText(panel, label, (x, y - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (230, 230, 230), 1, cv2.LINE_AA)

    def _draw_button(self, panel, x, y, w, h, text, button_id):
        # Save button rectangles for click detection
        if not hasattr(self, "_buttons"):
            self._buttons = {}
        self._buttons[button_id] = (x, y, x + w, y + h)

        # Color depends on last click highlight
        is_active = (self._clicked_button == button_id and self._mouse_down)
        bg = (70, 70, 70) if not is_active else (120, 120, 120)
        cv2.rectangle(panel, (x, y), (x + w, y + h), bg, -1)
        cv2.rectangle(panel, (x, y), (x + w, y + h), (180, 180, 180), 1)

        # Centered text
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        tx = x + (w - tw) // 2
        ty = y + (h + th) // 2
        cv2.putText(panel, text, (tx, ty),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (240, 240, 240), 1, cv2.LINE_AA)

    def _handle_button(self, button_id: str):
        if button_id == "FWD":
            self.vel.linear += LINEAR_STEP
        elif button_id == "BACK":
            self.vel.linear -= LINEAR_STEP
        elif button_id == "LEFT":
            self.vel.angular += ANGULAR_STEP
        elif button_id == "RIGHT":
            self.vel.angular -= ANGULAR_STEP
        elif button_id == "STOP":
            self.vel.stop()
        elif button_id == "ZANG":
            self.vel.angular = 0.0
        elif button_id == "ZLIN":
            self.vel.linear = 0.0
        elif button_id == "QUIT":
            self.running = False

        self.vel.clamp()

    def mouse_cb(self, event, x, y, flags, userdata):
        """
        Mouse callback on the combined window.
        Buttons live on the right panel only. Need to offset x by FPV width.
        """
        # Determine FPV width from current frame if available
        with self._frame_lock:
            frame = self._last_frame
        fpv_w = frame.shape[1] if frame is not None else 640

        # Only consider clicks in panel area
        in_panel = x >= fpv_w
        if not in_panel:
            return

        # Convert to panel coordinates
        px = x - fpv_w
        py = y

        if event == cv2.EVENT_LBUTTONDOWN:
            self._mouse_down = True
            self._clicked_button = self._hit_test_button(px, py)
            if self._clicked_button:
                self._handle_button(self._clicked_button)

        elif event == cv2.EVENT_LBUTTONUP:
            self._mouse_down = False
            self._clicked_button = None

        elif event == cv2.EVENT_MOUSEMOVE:
            # Optional: could implement hover effects
            pass

    def _hit_test_button(self, px, py):
        if not hasattr(self, "_buttons"):
            return None
        for bid, (x1, y1, x2, y2) in self._buttons.items():
            if x1 <= px <= x2 and y1 <= py <= y2:
                return bid
        return None

    # ----------------------------
    # Main UI loop
    # ----------------------------
    def ui_loop(self):
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
        
        cv2.setMouseCallback(WINDOW_NAME, self.mouse_cb)

        # Simple rate limit for UI refresh
        ui_dt = 1.0 / 30.0  # 30 FPS UI
        last = time.time()

        while self.running and rclpy.ok():
            now = time.time()
            if now - last < ui_dt:
                time.sleep(0.001)
                continue
            last = now

            # Get latest frame
            with self._frame_lock:
                frame = None if self._last_frame is None else self._last_frame.copy()

            # Compose and show
            combined = self.draw_ui(frame)
            cv2.imshow(WINDOW_NAME, combined)

            # Key handling
            key = cv2.waitKey(1)
            self.apply_key(key)

        # Ensure stop on exit (safety)
        self.vel.stop()
        self.publish_cmd()

        try:
            cv2.destroyAllWindows()
        except Exception:
            pass

        self.get_logger().info("UI loop finished. Exiting...")

    def shutdown(self):
        # Called by main to cleanly stop
        self.running = False
        self.vel.stop()
        self.publish_cmd()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image_topic", default="/rgb", help="Image topic (sensor_msgs/Image)")
    parser.add_argument("--cmd_vel_topic", default="/cmd_vel", help="CmdVel topic (geometry_msgs/Twist)")
    args = parser.parse_args()

    rclpy.init()
    node = FPVControlBoard(image_topic=args.image_topic, cmd_vel_topic=args.cmd_vel_topic)

    # Spin rclpy in a background thread (so OpenCV UI loop can run in main thread safely)
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

