# dori_perception

The robot uses two independent wide-angle USB RGB cameras, front and rear.
`perception.launch.py` starts the native `rgb_camera_node` and a person detector
for each camera. See [camera setup](../dori_perception_camera/README.md).

Front outputs retain `/dori/hri/persons`, `/dori/hri/tracking_state` and optional
`/dori/hri/annotated_image`. Rear outputs use `/dori/hri/rear/` with the same suffixes.
Each detection carries `camera_id`, a camera-local `track_id`, pixel bounding box,
normalized center/area and confidence. Track IDs are independent across cameras.
`distance_m` is null and `distance_source` is `unavailable`; bounding-box size is
not a metric distance. `target_id` stays null and interaction tracking state stays
`idle`, with `metric_tracking_available=false`. These observations never identify
the paired phone owner or start an interaction/follow action.

`hri/set_follow_mode` rejects enable requests and accepts disable requests.
No follow offset is emitted until a validated metric sensing/association pipeline
is implemented. LiDAR measurements are not automatically assigned to image tracks.

The smartphone gateway owns `hri/interaction_trigger`, true only while the paired
phone WebSocket is active. Optional gesture and expression inference follows that
gate. The visitor BT does not accept gesture/wake/microphone-based motion.
Gesture, expression and landmark features remain opt-in.

Landmarks provide semantic context with explicit unknown range. Directions require
matching calibration and distortion correction. Localization candidates require
finite positive measured range and a calibrated direction, so RGB-only detections
cannot generate range-based localization. There are no depth subscriptions.
