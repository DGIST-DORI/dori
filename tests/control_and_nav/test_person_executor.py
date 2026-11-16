"""Exercise actual ROS callback groups with a deliberately blocked model."""
import threading
from unittest.mock import Mock

import numpy as np
import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_srvs.srv import SetBool

from dori_perception import person_detection_node as people


def test_images_and_follow_service_remain_responsive_during_inference(monkeypatch):
    started, release, received_latest, finished_latest = [threading.Event() for _ in range(4)]
    processed = []

    def infer(frame, **kwargs):
        number = int(frame[0, 0, 0])
        processed.append(number)
        if number == 1:
            started.set()
            assert release.wait(3), "Test did not release blocked inference"
        if number == 3:
            finished_latest.set()
        return []

    model = Mock(track=Mock(side_effect=infer))
    model.predictor = None
    monkeypatch.setattr(people, 'YOLO', Mock(return_value=model))

    class ObservedNode(people.PersonDetectionNode):
        def image_callback(self, msg):
            super().image_callback(msg)
            if msg.data[0] == 3:
                received_latest.set()

    rclpy.init(args=['--ros-args', '-p', 'max_frame_age_sec:=5.0',
                    '-p', 'max_inference_fps:=30.0'])
    detector = peer = executor = thread = None
    try:
        detector = ObservedNode()
        peer = Node('person_test_peer')
        publisher = peer.create_publisher(Image, 'camera/front/color/image_raw', 1)
        client = peer.create_client(SetBool, 'hri/set_follow_mode')
        executor = MultiThreadedExecutor(num_threads=2)
        executor.add_node(detector)
        executor.add_node(peer)
        thread = threading.Thread(target=executor.spin)
        thread.start()
        assert client.wait_for_service(timeout_sec=2)
        # Seed inference directly, then deliver the newer frame over real DDS.
        detector.image_callback(detector.bridge.cv2_to_imgmsg(np.full((8, 8, 3), 1, np.uint8), 'bgr8'))
        assert started.wait(2)
        detector.image_callback(detector.bridge.cv2_to_imgmsg(np.full((8, 8, 3), 2, np.uint8), 'bgr8'))
        publisher.publish(detector.bridge.cv2_to_imgmsg(np.full((8, 8, 3), 3, np.uint8), 'bgr8'))
        assert received_latest.wait(2), 'Image reception was blocked by inference'
        responded = threading.Event()
        future = client.call_async(SetBool.Request(data=True))
        future.add_done_callback(lambda result: responded.set())
        assert responded.wait(2), 'Follow service was blocked by inference'
        assert future.result().success is False
        release.set()
        assert finished_latest.wait(2)
        assert processed == [1, 3]
    finally:
        release.set()
        if executor is not None:
            executor.shutdown()
        if thread is not None:
            thread.join(timeout=3)
        for node in (detector, peer):
            if node is not None:
                node.destroy_node()
        rclpy.shutdown()
