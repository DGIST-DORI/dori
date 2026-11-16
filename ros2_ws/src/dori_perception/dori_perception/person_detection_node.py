#!/usr/bin/env python3
"""RGB person observations. Image tracks do not identify the phone session owner."""
import json
import math
import time

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image
from std_msgs.msg import String
from std_srvs.srv import SetBool

from dori_perception.rgb_tracking import (
    LatestImage, VisualTrackMemory, image_is_fresh, person_observations, stamp_ns,
)

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None


class PersonDetectionNode(Node):
    def __init__(self):
        super().__init__("person_detection_node")
        defaults = {
            "model_path": "yolov8n.pt", "confidence_threshold": 0.5,
            "device": "cpu", "visualize": False, "tracker_config": "bytetrack.yaml",
            "lost_timeout_sec": 5.0, "max_frame_age_sec": 1.0, "max_inference_fps": 10.0,
            "camera_id": "front",
            "topics.color_image_sub": "camera/front/color/image_raw",
            "topics.persons_pub": "hri/persons",
            "topics.tracking_state_pub": "hri/tracking_state",
            "topics.annotated_pub": "hri/annotated_image",
            "services.follow_mode_service": "hri/set_follow_mode",
        }
        for key, value in defaults.items():
            self.declare_parameter(key, value)
        value = lambda key: self.get_parameter(key).value
        for key in ("lost_timeout_sec", "max_frame_age_sec", "max_inference_fps"):
            if not math.isfinite(value(key)) or value(key) <= 0:
                raise ValueError(f"{key} must be finite and positive")
        if not 0 <= value("confidence_threshold") <= 1:
            raise ValueError("confidence_threshold must be in [0, 1]")
        if YOLO is None:
            raise RuntimeError("Person detection requires ultralytics and local model weights")
        self.model = YOLO(value("model_path"))
        self.model.to(value("device"))
        self.conf_thresh = value("confidence_threshold")
        self.tracker_config = value("tracker_config")
        self.camera_id = value("camera_id")
        self.visualize = value("visualize")
        self.max_frame_age_sec = value("max_frame_age_sec")
        self.track_memory = VisualTrackMemory(value("lost_timeout_sec"))
        self.inbox = LatestImage()
        self._last_stamp_ns = 0
        self._last_inference_at = None
        self._last_shape = None
        self._track_epoch = 0
        self.bridge = CvBridge()
        self.create_subscription(Image, value("topics.color_image_sub"), self.image_callback,
                                 QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT))
        self.create_service(SetBool, value("services.follow_mode_service"), self._follow_mode_service_callback)
        self.persons_detail_pub = self.create_publisher(String, value("topics.persons_pub"), 10)
        self.tracking_state_pub = self.create_publisher(String, value("topics.tracking_state_pub"), 10)
        if self.visualize:
            self.annotated_pub = self.create_publisher(Image, value("topics.annotated_pub"), 1)
        # Reception/services remain responsive while one inference runs. The separate
        # mutually-exclusive group prevents concurrent calls into the YOLO tracker.
        self._inference_group = MutuallyExclusiveCallbackGroup()
        self.create_timer(1.0 / value("max_inference_fps"), self._process_latest,
                          callback_group=self._inference_group)

    def _follow_mode_service_callback(self, request, response):
        # Preserve the service contract while explicitly refusing unsupported metric follow.
        response.success = not request.data
        response.message = ("Following requires a validated metric range source; RGB only"
                            if request.data else "Following disabled")
        return response

    def image_callback(self, msg):
        self.inbox.put(msg, time.monotonic())

    def _process_latest(self):
        pending = self.inbox.take()
        if pending is not None:
            self._process_image(*pending)

    def _fresh(self, msg, received_at):
        return image_is_fresh(msg, self.get_clock().now().nanoseconds,
                              received_at, time.monotonic(), self.max_frame_age_sec)

    def _reset_tracks(self):
        predictor = getattr(self.model, "predictor", None)
        for tracker in getattr(predictor, "trackers", ()):
            tracker.reset()
        self.track_memory.clear()
        self._track_epoch += 1

    def _process_image(self, msg, received_at):
        stamp_value = stamp_ns(msg)
        if not self._fresh(msg, received_at):
            return
        if stamp_value and stamp_value <= self._last_stamp_ns:
            return  # Duplicate/out-of-order source frames must not advance the tracker.
        if stamp_value:
            self._last_stamp_ns = stamp_value
        try:
            frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
            height, width = frame.shape[:2]
            if height <= 0 or width <= 0:
                raise ValueError("Empty RGB image")
            now = time.monotonic()
            if self._last_inference_at is not None and (
                    now - self._last_inference_at >= self.track_memory.lost_timeout_sec
                    or self._last_shape != (height, width)):
                self._reset_tracks()
            results = self.model.track(frame, conf=self.conf_thresh, classes=[0],
                                       tracker=self.tracker_config, persist=True, verbose=False)
            detections = person_observations(results, width, height, self.camera_id)
            self._last_inference_at = now
            self._last_shape = (height, width)
        except Exception as error:
            self.get_logger().error(f"Person inference failed: {error}")
            return  # No heartbeat on failed inference.
        if not self._fresh(msg, received_at):
            return  # Slow inference cannot turn an old frame into a fresh heartbeat.
        visual_tracking = self.track_memory.update(detections, now)
        visual_tracking["epoch"] = self._track_epoch
        stamp = {"sec": msg.header.stamp.sec, "nanosec": msg.header.stamp.nanosec}
        self.persons_detail_pub.publish(String(data=json.dumps({
            "camera_id": self.camera_id, "stamp": stamp, "count": len(detections),
            "target_id": None, "state": "idle", "detections": detections,
            "visual_tracking": visual_tracking,
        })))
        # Legacy consumers must not interpret visual detections as a tracked visitor.
        self.tracking_state_pub.publish(String(data=json.dumps({
            "camera_id": self.camera_id, "stamp": stamp, "state": "idle",
            "target_id": None, "last_distance_m": None,
            "lost_elapsed_sec": 0.0, "lost_timeout_sec": 0.0,
            "metric_tracking_available": False,
            "visual_tracking": visual_tracking,
        })))
        if self.visualize:
            for detection in detections:
                x1, y1, x2, y2 = detection["bbox"]
                cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 200, 0), 2)
                cv2.putText(frame, f'{self.camera_id} ID:{detection["track_id"]} distance: N/A',
                            (x1, max(y1 - 8, 12)), cv2.FONT_HERSHEY_SIMPLEX, .5, (255, 200, 0), 1)
            try:
                image = self.bridge.cv2_to_imgmsg(frame, encoding="bgr8")
                image.header = msg.header
                self.annotated_pub.publish(image)
            except Exception as error:
                self.get_logger().warning(f"Person annotation failed: {error}")


def main(args=None):
    rclpy.init(args=args)
    node = None
    executor = MultiThreadedExecutor(num_threads=2)
    try:
        node = PersonDetectionNode()
        executor.add_node(node)
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
