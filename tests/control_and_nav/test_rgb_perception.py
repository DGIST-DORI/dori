"""RGB-only detections never fabricate range, target identity or localization."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from sensor_msgs.msg import CameraInfo, Image
from std_srvs.srv import SetBool
from dori_perception.person_detection_node import PersonDetectionNode
from dori_perception.landmark_detection_node import LandmarkDetectionNode


@pytest.mark.parametrize("camera_id", ["front", "rear"])
def test_person_detections_keep_image_tracks_without_metric_target(camera_id):
    box = SimpleNamespace(xyxy=np.array([[10, 20, 90, 180]]),
                          conf=[.9], id=[7])
    node = SimpleNamespace(
        bridge=Mock(), model=Mock(), conf_thresh=.5, tracker_config="bytetrack.yaml",
        camera_id=camera_id, visualize=False, persons_detail_pub=Mock(),
        tracking_state_pub=Mock(), get_logger=Mock(),
    )
    node.bridge.imgmsg_to_cv2.return_value = np.zeros((200, 100, 3), dtype=np.uint8)
    node.model.track.return_value = [SimpleNamespace(boxes=[box])]
    message = Image()
    message.header.stamp.sec = 123
    PersonDetectionNode.image_callback(node, message)
    people = json.loads(node.persons_detail_pub.publish.call_args.args[0].data)
    assert people['camera_id'] == camera_id
    assert people['count'] == 1 and people['target_id'] is None
    assert people['stamp']['sec'] == 123
    person = people['detections'][0]
    assert person['track_id'] == 7
    assert person['distance_m'] is None and person['distance_source'] == 'unavailable'
    tracking = json.loads(node.tracking_state_pub.publish.call_args.args[0].data)
    assert tracking['state'] == 'idle' and tracking['last_distance_m'] is None
    assert tracking['metric_tracking_available'] is False
    node.model.track.side_effect = RuntimeError('inference unavailable')
    node.persons_detail_pub.reset_mock()
    PersonDetectionNode.image_callback(node, message)
    node.persons_detail_pub.publish.assert_not_called()


def test_rgb_follow_enable_is_rejected_and_disable_is_idempotent():
    for enabled in (True, False):
        result = PersonDetectionNode._follow_mode_service_callback(
            None, SetBool.Request(data=enabled), SetBool.Response())
        assert result.success is (not enabled)


def camera_info(model='equidistant'):
    info = CameraInfo(width=640, height=480, distortion_model=model)
    info.k = [320., 0., 320., 0., 320., 240., 0., 0., 1.]
    info.d = [0.] * (4 if model == 'equidistant' else 5)
    return info


def test_landmark_direction_requires_calibration_for_actual_resolution():
    node = SimpleNamespace(_camera_intrinsics=None)
    direction = LandmarkDetectionNode._pixel_to_direction
    assert direction(node, 400, 240, 640, 480) is None
    node._camera_intrinsics = CameraInfo(width=640, height=480)
    assert direction(node, 400, 240, 640, 480) is None
    node._camera_intrinsics = camera_info()
    assert direction(node, 400, 240, 1280, 720) is None
    assert direction(node, 320, 240, 640, 480) == {'x': 0., 'y': 0.}
    # Zero fisheye coefficients still use the equidistant projection, not pinhole x/f.
    ray = direction(node, 400, 240, 640, 480)
    assert ray['x'] == pytest.approx(np.tan(.25))
    node._camera_intrinsics = camera_info('plumb_bob')
    assert direction(node, 400, 240, 640, 480)['x'] == pytest.approx(.25)


@pytest.mark.parametrize('distance', [None, float('nan'), float('inf'), 0., -1.])
def test_landmarks_without_valid_range_never_publish_localization(distance):
    node = SimpleNamespace(loc_conf_thresh=.6, localization_pub=Mock())
    landmark = dict(landmark_id='sign', display_name='sign', map_position={'x': 1, 'y': 2},
                    distance_m=distance, direction={'x': 0., 'y': 0.}, confidence=.9)
    LandmarkDetectionNode._publish_localization_candidates(node, [landmark], SimpleNamespace(sec=1, nanosec=0))
    node.localization_pub.publish.assert_not_called()
