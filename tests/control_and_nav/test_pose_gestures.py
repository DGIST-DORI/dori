"""Pose observations require fresh, visible, unambiguous and sustained evidence."""
from collections import deque
import json
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from sensor_msgs.msg import Image
from std_msgs.msg import Bool

from dori_perception import gesture_recognition_node as gestures
from dori_perception.pose_gestures import raised_hands


def pose(left=False, right=False):
    landmarks = [SimpleNamespace(x=.5, y=.5, visibility=.9, presence=.9) for _ in range(33)]
    landmarks[15].y = .3 if left else .7
    landmarks[16].y = .3 if right else .7
    return landmarks


@pytest.mark.parametrize('left,right,expected', [
    (False, False, 'NONE'), (True, False, 'LEFT_HAND_RAISED'),
    (False, True, 'RIGHT_HAND_RAISED'), (True, True, 'BOTH_HANDS_RAISED'),
])
def test_raised_hands(left, right, expected):
    assert raised_hands([pose(left, right)]) == expected


@pytest.mark.parametrize('field,value', [
    ('visibility', .2), ('presence', .2), ('x', -1), ('y', float('nan')),
    ('visibility', None), ('presence', float('inf')), ('y', .48),
])
def test_occlusion_invalid_landmarks_and_small_motion_are_rejected(field, value):
    landmarks = pose(left=True)
    setattr(landmarks[15], field, value)
    assert raised_hands([landmarks]) == 'NONE'


def test_no_person_or_multiple_people_cannot_select_an_arbitrary_pose():
    assert raised_hands([]) == 'NONE'
    assert raised_hands([pose(left=True), pose(right=True)]) == 'NONE'
    assert raised_hands([[SimpleNamespace()]]) == 'NONE'


@pytest.fixture
def node(monkeypatch):
    monkeypatch.setattr(gestures, 'mp', SimpleNamespace(Image=Mock(), ImageFormat=SimpleNamespace(SRGB=0)), raising=False)
    monkeypatch.setattr(gestures.time, 'monotonic', lambda: 10.)
    node = SimpleNamespace(
        is_active=True, active_on_trigger=True, backend='pose', pose=Mock(), hands=None,
        bridge=Mock(), visualize=False, max_frame_age_sec=1., _last_stamp_ns=0,
        _last_timestamp_ms=-1, _last_frame_at=None, _gesture_history=deque(maxlen=3),
        _wrist_x_history=deque(maxlen=10), confirm_frames=3,
        pose_min_confidence=.6, raised_hand_margin=.03, gesture_pub=Mock(),
        command_pub=Mock(), trigger_pub=Mock(), get_logger=Mock(),
        get_clock=lambda: SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=11_000_000_000)),
    )
    for name in ('image_callback', '_fresh', '_confirm_gesture', '_publish_gesture',
                 '_gesture_to_command', '_trigger_callback'):
        setattr(node, name, MethodType(getattr(gestures.GestureRecognitionNode, name), node))
    node.bridge.imgmsg_to_cv2.return_value = np.zeros((100, 100, 3), dtype=np.uint8)
    node.pose.detect_for_video.return_value = SimpleNamespace(pose_landmarks=[pose(left=True)])
    return node


def frame(nanosec=0, sec=10):
    message = Image()
    message.header.stamp.sec = sec
    message.header.stamp.nanosec = nanosec
    return message


def test_pose_confirmation_uses_distinct_frames_and_never_issues_commands(node):
    for timestamp in (0, 0, 1, 1):
        node.image_callback(frame(timestamp))
    assert json.loads(node.gesture_pub.publish.call_args.args[0].data)['gesture'] == 'NONE'
    node.image_callback(frame(2))
    output = json.loads(node.gesture_pub.publish.call_args.args[0].data)
    assert output['gesture'] == 'LEFT_HAND_RAISED'
    assert output['target_id'] is None and output['backend'] == 'pose'
    node.command_pub.publish.assert_not_called()
    node.trigger_pub.publish.assert_not_called()
    assert [call.args[1] for call in node.pose.detect_for_video.call_args_list] == [10000, 10001, 10002]


def test_trigger_off_skips_inference_and_resets_confirmation(node):
    node.image_callback(frame())
    node.image_callback(frame(1))
    node._trigger_callback(Bool(data=False))
    assert not node._gesture_history
    node.image_callback(frame(2))
    assert node.pose.detect_for_video.call_count == 2
    node._trigger_callback(Bool(data=True))
    node.image_callback(frame(3))
    assert json.loads(node.gesture_pub.publish.call_args.args[0].data)['gesture'] == 'NONE'


@pytest.mark.parametrize('failure', ['stale', 'slow', 'exception', 'ambiguous'])
def test_invalid_input_breaks_confirmation(node, monkeypatch, failure):
    node.image_callback(frame())
    node.image_callback(frame(1))
    if failure == 'stale':
        node.get_clock = lambda: SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=15_000_000_000))
    elif failure == 'slow':
        def slow(*args):
            monkeypatch.setattr(gestures.time, 'monotonic', lambda: 12.)
            return SimpleNamespace(pose_landmarks=[pose(left=True)])
        node.pose.detect_for_video.side_effect = slow
    elif failure == 'exception':
        node.pose.detect_for_video.side_effect = RuntimeError('bad model result')
    else:
        node.pose.detect_for_video.return_value = SimpleNamespace(pose_landmarks=[pose(left=True), pose(right=True)])
    node.image_callback(frame(2))
    assert node._confirm_gesture() == gestures.Gesture.NONE
    node.command_pub.publish.assert_not_called()
    node.trigger_pub.publish.assert_not_called()
