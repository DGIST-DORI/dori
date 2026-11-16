#!/usr/bin/env python3
"""RGB person observations. Image tracks do not identify the phone session owner."""
import json

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String
from std_srvs.srv import SetBool

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
        if YOLO is None:
            raise RuntimeError("Person detection requires ultralytics and local model weights")
        self.model = YOLO(value("model_path"))
        self.model.to(value("device"))
        self.conf_thresh = value("confidence_threshold")
        self.tracker_config = value("tracker_config")
        self.camera_id = value("camera_id")
        self.visualize = value("visualize")
        self.bridge = CvBridge()
        self.create_subscription(Image, value("topics.color_image_sub"), self.image_callback, 1)
        self.create_service(SetBool, value("services.follow_mode_service"), self._follow_mode_service_callback)
        self.persons_detail_pub = self.create_publisher(String, value("topics.persons_pub"), 10)
        self.tracking_state_pub = self.create_publisher(String, value("topics.tracking_state_pub"), 10)
        if self.visualize:
            self.annotated_pub = self.create_publisher(Image, value("topics.annotated_pub"), 1)

    def _follow_mode_service_callback(self, request, response):
        # Preserve the service contract while explicitly refusing unsupported metric follow.
        response.success = not request.data
        response.message = ("Following requires a validated metric range source; RGB only"
                            if request.data else "Following disabled")
        return response

    def image_callback(self, msg):
        try:
            frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
            height, width = frame.shape[:2]
            results = self.model.track(frame, conf=self.conf_thresh, classes=[0],
                                       tracker=self.tracker_config, persist=True, verbose=False)
        except Exception as error:
            self.get_logger().error(f"Person inference failed: {error}")
            return  # No heartbeat on failed inference.
        detections = []
        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                track_id = int(box.id[0]) if box.id is not None else -1
                detections.append({
                    "camera_id": self.camera_id,
                    "track_id": track_id,
                    "bbox": [x1, y1, x2, y2],
                    "confidence": round(float(box.conf[0]), 3),
                    "center_norm": [round((x1 + x2) / (2 * width), 3),
                                    round((y1 + y2) / (2 * height), 3)],
                    "bbox_area_norm": round((x2 - x1) * (y2 - y1) / (width * height), 4),
                    "distance_m": None, "distance_source": "unavailable",
                })
        stamp = {"sec": msg.header.stamp.sec, "nanosec": msg.header.stamp.nanosec}
        self.persons_detail_pub.publish(String(data=json.dumps({
            "camera_id": self.camera_id, "stamp": stamp, "count": len(detections),
            "target_id": None, "state": "idle", "detections": detections,
        })))
        # Legacy consumers must not interpret visual detections as a tracked visitor.
        self.tracking_state_pub.publish(String(data=json.dumps({
            "camera_id": self.camera_id, "stamp": stamp, "state": "idle",
            "target_id": None, "last_distance_m": None,
            "lost_elapsed_sec": 0.0, "lost_timeout_sec": 0.0,
            "metric_tracking_available": False,
        })))
        if self.visualize:
            for detection in detections:
                x1, y1, x2, y2 = detection["bbox"]
                cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 200, 0), 2)
                cv2.putText(frame, f'{self.camera_id} ID:{detection["track_id"]} distance: N/A',
                            (x1, max(y1 - 8, 12)), cv2.FONT_HERSHEY_SIMPLEX, .5, (255, 200, 0), 1)
            image = self.bridge.cv2_to_imgmsg(frame, encoding="bgr8")
            image.header = msg.header
            self.annotated_pub.publish(image)


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = PersonDetectionNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
