"""RGB-only detections never fabricate range, target identity or localization."""
import json
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from sensor_msgs.msg import CameraInfo, Image
from std_srvs.srv import SetBool
from dori_perception.person_detection_node import PersonDetectionNode
from dori_perception.landmark_detection_node import LandmarkDetectionNode
from dori_perception.rgb_tracking import LatestImage, VisualTrackMemory, person_observations


@pytest.fixture
def person_node(monkeypatch):
    clock = SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=123_000_000_000))
    node = SimpleNamespace(
        bridge=Mock(), model=Mock(), conf_thresh=.5, tracker_config="bytetrack.yaml",
        camera_id="front", visualize=False, persons_detail_pub=Mock(),
        tracking_state_pub=Mock(), get_logger=Mock(), get_clock=lambda: clock,
        max_frame_age_sec=1., track_memory=VisualTrackMemory(), inbox=LatestImage(),
        _last_stamp_ns=0, _last_inference_at=None, _last_shape=None, _track_epoch=0,
    )
    node.model.predictor = None
    node.bridge.imgmsg_to_cv2.return_value = np.zeros((200, 100, 3), dtype=np.uint8)
    for name in ("_fresh", "_process_image", "_process_latest", "_reset_tracks", "image_callback"):
        setattr(node, name, MethodType(getattr(PersonDetectionNode, name), node))
    monkeypatch.setattr("dori_perception.person_detection_node.time.monotonic", lambda: 10.)
    return node


@pytest.mark.parametrize("camera_id", ["front", "rear"])
def test_person_detections_keep_image_tracks_without_metric_target(camera_id, person_node):
    box = SimpleNamespace(xyxy=np.array([[10, 20, 90, 180]]),
                          conf=[.9], id=[7])
    node = person_node
    node.camera_id = camera_id
    node.model.track.return_value = [SimpleNamespace(boxes=[box])]
    message = Image()
    message.header.stamp.sec = 123
    PersonDetectionNode.image_callback(node, message)
    node._process_latest()
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
    assert tracking['visual_tracking']['state'] == 'tracking'
    assert tracking['visual_tracking']['tracks'][0]['track_id'] == 7
    node.model.track.side_effect = RuntimeError('inference unavailable')
    node.persons_detail_pub.reset_mock()
    message.header.stamp.sec = 0
    PersonDetectionNode.image_callback(node, message)
    node._process_latest()
    node.persons_detail_pub.publish.assert_not_called()


def test_latest_image_is_consumed_once_and_duplicates_are_not_reinferred(person_node):
    node = person_node
    node.model.track.return_value = []
    first, latest = Image(), Image()
    first.header.stamp.sec = 122
    latest.header.stamp.sec = 123
    node.image_callback(first)
    node.image_callback(latest)
    node._process_latest()
    node._process_latest()
    node.bridge.imgmsg_to_cv2.assert_called_once_with(latest, desired_encoding="bgr8")
    for message in (latest, first):
        node.image_callback(message)
        node._process_latest()
    assert node.model.track.call_count == 1


@pytest.mark.parametrize('source_sec,received_at', [(121, 10.), (124, 10.), (123, 8.), (0, 8.)])
def test_stale_future_and_delayed_frames_publish_no_heartbeat(person_node, source_sec, received_at):
    message = Image()
    message.header.stamp.sec = source_sec
    person_node._process_image(message, received_at)
    person_node.model.track.assert_not_called()
    person_node.persons_detail_pub.publish.assert_not_called()
    person_node.tracking_state_pub.publish.assert_not_called()


def test_result_that_ages_out_during_inference_publishes_no_heartbeat(person_node, monkeypatch):
    now = [10.]
    monkeypatch.setattr("dori_perception.person_detection_node.time.monotonic", lambda: now[0])
    def slow_inference(*args, **kwargs):
        now[0] += 2
        return []
    person_node.model.track.side_effect = slow_inference
    person_node._process_image(Image(), 10.)
    person_node.persons_detail_pub.publish.assert_not_called()
    person_node.tracking_state_pub.publish.assert_not_called()


@pytest.mark.parametrize('last_seen,last_shape', [(4., (200, 100)), (9., (400, 200))])
def test_tracker_is_reset_after_outage_or_resolution_change(person_node, last_seen, last_shape):
    node = person_node
    tracker = Mock()
    node.model.predictor = SimpleNamespace(trackers=[tracker])
    node.model.track.return_value = []
    node._last_inference_at = last_seen
    node._last_shape = last_shape
    node.track_memory.update([dict(track_id=7, bbox=[0, 0, 1, 1])], 9.)
    node._process_image(Image(), 10.)
    tracker.reset.assert_called_once()
    output = json.loads(node.persons_detail_pub.publish.call_args.args[0].data)
    assert output['visual_tracking'] == dict(state='idle', lost_timeout_sec=5., tracks=[], epoch=1)


def test_visual_tracks_acquire_lose_recover_and_expire_without_iou_id_reassignment():
    memory = VisualTrackMemory(5.)
    person = dict(track_id=7, bbox=[0, 0, 10, 20])
    assert memory.update([], 0.)['state'] == 'idle'
    assert memory.update([person], 1.)['state'] == 'tracking'
    assert memory.update([], 2.)['tracks'][0]['state'] == 'lost'
    assert memory.update([person], 3.)['tracks'][0]['lost_elapsed_sec'] == 0
    # An identical box with a new ID is still a new observation, never an ID repair.
    changed_id = dict(person, track_id=8)
    result = memory.update([changed_id], 4.)
    assert [(t['track_id'], t['state']) for t in result['tracks']] == [(7, 'lost'), (8, 'tracking')]
    assert [t['track_id'] for t in memory.update([], 8.)['tracks']] == [8]
    assert memory.update([], 9.)['state'] == 'idle'
    assert memory.update([dict(person, track_id=-1)], 10.)['tracks'] == []


def test_invalid_boxes_are_dropped_and_valid_boxes_clipped():
    def box(coords, track_id=None, confidence=.9):
        return SimpleNamespace(xyxy=np.array([coords]), id=track_id, conf=[confidence])
    boxes = [box([-10, -20, 110, 220], [7]), box([40, 30, 10, 50]),
             box([np.nan, 0, 1, 1]), box([101, 0, 120, 20]),
             box([0, 0, 10, 10], confidence=np.inf), box([0, 0, 10, 10])]
    result = person_observations([SimpleNamespace(boxes=boxes)], 100, 200, 'rear')
    assert len(result) == 2
    assert result[0]['bbox'] == [0, 0, 100, 200]
    assert result[0]['bbox_area_norm'] == 1.
    assert result[0]['center_norm'] == [.5, .5]
    assert result[1]['track_id'] == -1


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
