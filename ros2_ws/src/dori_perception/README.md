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

## RGB tracking and frame handling

The person node receives images independently of inference, with a one-image
mailbox and a single inference callback. Intermediate frames are replaced by the
latest image; a consumed image is never inferred again by the timer. The default
limit is 10 inference starts per second per camera. Input QoS is best-effort with
depth 1, compatible with reliable or best-effort camera publishers.

Images older than 1 second (including inference time), future-dated images, and
duplicate/out-of-order nonzero source stamps do not publish observations or a
readiness heartbeat. Unstamped images use local receipt age. Source stamps must
use the same ROS clock as the detector; restart perception after rewinding a bag
or resetting its clock. Stream silence produces no heartbeat or synthetic empty
detection; consumers must expire observations using their source stamp.

Both person output topics include an additive `visual_tracking` object:

```json
{"state":"lost","epoch":0,"lost_timeout_sec":5.0,
 "tracks":[{"track_id":7,"bbox":[10,20,90,180],"state":"lost","lost_elapsed_sec":0.3}]}
```

Each camera retains missing track IDs for 5 seconds from their last observation.
An observed ID immediately becomes `tracking`, absent retained IDs become `lost`,
and the aggregate becomes `idle` once none remain. Only current detections count
toward `count`/`detections`; retained boxes are historical observations. The same
tracker ID can resume before expiry. A different ID is never relabeled using IoU.
YOLO tracker IDs themselves can switch; they are not proof of a person's identity.
An input gap of at least the timeout, or an image resolution change, resets the
tracker and memory and increments `epoch`. Interpret IDs within the camera, node
lifetime and epoch. The top-level interaction `state` remains `idle` as above.

Launch options, also accepted by the bringup deployment YAML:

| Option | Default | Purpose |
| --- | --- | --- |
| `person_tracker` | `bytetrack.yaml` | Ultralytics tracker YAML name/path; `botsort.yaml` can be evaluated on recorded RGB footage. |
| `person_lost_timeout_sec` | `5.0` | Visual observation memory, in seconds; separate from the tracker's frame-based buffer. |
| `person_max_inference_fps` | `10.0` | Maximum person inference rate per camera. |
| `perception_max_frame_age_sec` | `1.0` | Maximum accepted input/result age for person and gesture nodes. |

Keep ByteTrack as the existing default until representative footage establishes
whether BoT-SORT improves ID continuity at an acceptable CPU cost. Tracker
configuration and persistent frame sequences follow the
[Ultralytics tracking API](https://docs.ultralytics.com/modes/track/).

## Optional raised-hand observations

The `gesture_backend` option selects `hands` (existing finger gestures, default)
or `pose` (body-pose raised hands). The pose backend uses the
[MediaPipe Pose Landmarker Tasks API](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker/python),
with strictly increasing VIDEO timestamps. Install the perception requirements
and supply a local `pose_landmarker_lite.task` model, then configure:

```yaml
common:
  enable_gesture: true
  gesture_backend: pose
  pose_model_path: ${DORI_ROOT}/.state/vision/pose_landmarker_lite.task
```

The front camera reports `LEFT_HAND_RAISED`, `RIGHT_HAND_RAISED`,
`BOTH_HANDS_RAISED`, or `NONE` on `hri/gesture`. Left/right refer to the person's
anatomical side. Wrists must be above their corresponding eyes by a normalized
margin of 0.03, with visibility and presence at least 0.6. Three distinct,
consecutive frames must agree. Two detected poses, missing/occluded landmarks,
stale input, inference failures and session deactivation break confirmation.
The model is configured to detect up to two poses to expose ambiguity; it cannot
guarantee that every person in the image was detected.

Raised hands are unassociated observations (`target_id=null`), never commands,
wake events, metric ranges or phone-owner identification. The phone session still
gates inference. The pose backend does not require a hand model. Missing or
invalid selected models fail startup explicitly. No camera is opened here; the
existing ROS RGB streams supply both detection and gesture inference.

## Review of the standalone detect.py proposal

The separate acquisition/inference paths, lost-track memory and body gestures
transfer well to the RGB ROS pipeline. The following prototype behaviors do not:

- Initial lock-on computed `target_det` before selecting `target_id`, allowing
  the new target to enter `lost` in the same iteration. Track memory here records
  visible IDs before deriving state.
- Missing depth silently bypassed the proposed 3D association check. IoU alone
  cannot establish identity through crossings; no forced ID reassignment is used.
- Tracking a person in one camera did not associate the pose in another camera
  with that person. Front/rear IDs and phone-session ownership remain separate.
- Reusing cached images in an unthrottled loop could advance tracking and gesture
  confirmation without new evidence. Receipt buffering and stamp checks prevent
  this, and elapsed tracking time uses a monotonic clock.
- RealSense streams, depth ROI percentiles, 3D deprojection, metric proximity
  thresholds, Windows DirectShow capture and GUI loops do not apply to this
  Linux RGB-only ROS deployment.

Landmarks provide semantic context with explicit unknown range. Directions require
matching calibration and distortion correction. Localization candidates require
finite positive measured range and a calibrated direction, so RGB-only detections
cannot generate range-based localization. There are no depth subscriptions.
