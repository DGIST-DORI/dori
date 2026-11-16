"""Classify visible raised wrists in normalized RGB pose landmarks."""
import math


def raised_hands(poses, min_confidence=0.6, margin=0.03):
    # Pose array order is not an identity. Suppress ambiguous multi-person input.
    if len(poses) != 1 or len(poses[0]) < 17:
        return "NONE"
    landmarks = poses[0]

    def raised(wrist_index, eye_index):
        wrist, eye = landmarks[wrist_index], landmarks[eye_index]
        for landmark in (wrist, eye):
            values = [landmark.x, landmark.y,
                      getattr(landmark, "visibility", None),
                      getattr(landmark, "presence", None)]
            if any(v is None or not math.isfinite(v) or not 0 <= v <= 1 for v in values):
                return False
            if min(values[2:]) < min_confidence:
                return False
        return wrist.y + margin < eye.y

    left, right = raised(15, 2), raised(16, 5)
    if left and right:
        return "BOTH_HANDS_RAISED"
    if left:
        return "LEFT_HAND_RAISED"
    if right:
        return "RIGHT_HAND_RAISED"
    return "NONE"
