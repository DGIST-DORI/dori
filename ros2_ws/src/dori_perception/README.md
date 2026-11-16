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

## Packages and models

Run these commands from the repository root, using the Python 3.10 `.venv` created
by the [root installation guide](../../../README.md#3-install-ros--python-dependencies).
Python requirements install libraries; `.pt` and `.task` weights are separate
assets. `scripts/build.sh` only installs the base runtime requirements. The
optional `scripts/install_dependencies.sh --vision` installs the base perception
requirements below, but does not download weights or install MediaPipe.

### 1. Select the PyTorch runtime

Install a matching torch/torchvision pair before the perception requirements.
For the first CPU bench test, this pair follows the
[PyTorch version table](https://pytorch.org/get-started/previous-versions/#v260):

```bash
.venv/bin/python -m pip install -c constraints-robot.txt \
  torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cpu
```

For GPU use on Jetson, choose wheels matching the installed JetPack from the
[NVIDIA installation guide](https://docs.nvidia.com/deeplearning/frameworks/install-pytorch-jetson-platform/index.html)
and a matching torchvision build. A generic PyPI/CPU wheel does not provide
Jetson CUDA support. Check both the CUDA build and availability:

```bash
.venv/bin/python -c 'import torch, torchvision; print(torch.__version__, torchvision.__version__, torch.version.cuda, torch.cuda.is_available())'
```

For a vendor-specific pair, save its installed versions before installing the
perception requirements and pass that file as an additional pip constraint:

```bash
mkdir -p .state/vision
.venv/bin/python - <<'PY'
from importlib.metadata import version
from pathlib import Path
Path('.state/vision/torch-constraints.txt').write_text(
    ''.join(f'{name}=={version(name)}\n' for name in ('torch', 'torchvision')))
PY
.venv/bin/python -m pip install -c .state/vision/torch-constraints.txt \
  -r ros2_ws/src/dori_perception/requirements.txt
```

This makes incompatible dependencies fail resolution rather than silently
replacing the selected pair. Do not use `--no-deps` for the whole stack.

### 2. Install the selected backends

```bash
.venv/bin/python -m pip install -r ros2_ws/src/dori_perception/requirements.txt
```

This installs YOLO, OpenCV and `lap` explicitly, so the first ByteTrack frame does
not need to install its assignment solver. Both requirements files include
`constraints-robot.txt`, preserving NumPy 1.24.4, SciPy 1.10.1 and OpenCV < 4.12
for Humble's binary extensions.

Only if using pose, hand gestures, or facial expressions:

```bash
.venv/bin/python -m pip install -r ros2_ws/src/dori_perception/requirements-mediapipe.txt
```

MediaPipe is pinned to 1.2.3, whose
[published files](https://pypi.org/project/mediapipe/1.2.3/#files) include Linux
aarch64 and x86_64 wheels usable on Ubuntu 22.04 / Python 3.10. Unlike older
0.10.18, this version does not require `protobuf<5`, which conflicts with current
Google TTS dependencies. MediaPipe includes `sounddevice` as a transitive package,
but these vision Tasks do not use it and do not require PortAudio or onboard
audio hardware. Use the project constraints; an unconstrained upgrade can break
the ROS NumPy ABI.

After installing the selected requirements, check package consistency:

```bash
.venv/bin/python -m pip check
```

### 3. Download and check models

```bash
# Required for RGB person detection; downloads only the person model.
.venv/bin/python scripts/prepare_perception.py

# Choose optional models to match the enabled features (flags can be combined).
.venv/bin/python scripts/prepare_perception.py --pose
# .venv/bin/python scripts/prepare_perception.py --hands
# .venv/bin/python scripts/prepare_perception.py --face

# Repeat validation without downloading model assets.
.venv/bin/python scripts/prepare_perception.py --pose --check-only
```

The helper uses versioned official Ultralytics/MediaPipe URLs, stores assets in
`.state/vision`, and preserves existing valid archives. Interrupted or invalid
downloads do not become final model files. Move an invalid existing model aside
and rerun. `--model-dir /absolute/path` chooses another directory;
`--download-only` stages models without importing ML libraries. No model weights
belong in Git, and rebuilding ROS does not redownload them.

The check exercises torchvision's compiled NMS operation, YOLO + ByteTrack on a
synthetic 640×480 image, and each selected MediaPipe Tasks model on two VIDEO
frames. It disables Ultralytics dependency auto-installation. No camera or ROS
node is started. It verifies loading/inference, not detection accuracy or
sustained real-time performance. `--device 0` checks YOLO on GPU after the GPU
runtime is ready; the default is `cpu`. For a GPU launch also set
`perception_device:=cuda:0` on bringup; checking a GPU does not change launch
defaults.

| Feature | Requirements | Preparation flag | Deployment setting |
| --- | --- | --- | --- |
| Person + ByteTrack | `requirements.txt` | none | `person_model: ${DORI_ROOT}/.state/vision/yolov8n.pt` |
| Raised hands | add `requirements-mediapipe.txt` | `--pose` | `gesture_backend: pose`, `pose_model_path: ${DORI_ROOT}/.state/vision/pose_landmarker_lite.task` |
| Finger/hand gestures | add `requirements-mediapipe.txt` | `--hands` | `gesture_backend: hands`, `hand_model_path: ${DORI_ROOT}/.state/vision/hand_landmarker.task` |
| Facial expression | add `requirements-mediapipe.txt` | `--face` | `face_model_path: ${DORI_ROOT}/.state/vision/face_landmarker.task` |

Use `enable_gesture: true` or `enable_expression: true` only for a prepared
backend. Pose does not need the hand model. Both cameras reuse the same person
weights but run separate trackers. The supplied COCO person model is not a
campus landmark model; keep `enable_landmark: false` until separate trained
weights and a landmark database are ready.

### 4. Bench test with one USB camera

After building, identify the capture endpoint (a second `/dev/videoN` from the
same camera may be metadata, not another camera):

```bash
v4l2-ctl --list-devices
ls -l /dev/v4l/by-id/
v4l2-ctl -d /dev/video0 --list-formats-ext
source scripts/env.sh
export ROS_DOMAIN_ID=97 ROS_LOCALHOST_ONLY=1
ros2 launch dori_bringup bringup.launch.py \
  dori_mode:=desktop enable_perception:=true enable_rear_camera:=false \
  front_device:=/dev/video0 camera_width:=640 camera_height:=480 camera_fps:=30 \
  person_model:="$PWD/.state/vision/yolov8n.pt" \
  enable_gesture:=false enable_expression:=false enable_landmark:=false \
  use_external_llm:=false
```

Replace `/dev/video0` with your capture endpoint, preferably its stable
`/dev/v4l/by-id/...-video-index0` path, and choose a supported resolution/FPS.
The command assumes the camera supports MJPG at 640×480/30 FPS. In a second
terminal, source the same environment and use the same domain settings:

```bash
source scripts/env.sh
export ROS_DOMAIN_ID=97 ROS_LOCALHOST_ONLY=1
ros2 topic hz /dori/camera/front/color/image_raw
# Run separately after stopping the hz command:
ros2 topic echo /dori/hri/persons --once
```

First verify image delivery and person observations with changing source stamps.
Then enable pose using the settings below and pair the phone; without an active
phone session, gesture inference is intentionally gated off. If the first CPU
inference takes longer than `perception_max_frame_age_sec`, its output is dropped;
the synthetic check and inference logs help distinguish that from camera failure.
The maximum inference FPS is a cap, not a throughput guarantee. Robot mode still
requires both cameras; leave the bench profile only after connecting and checking
the rear camera too.

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
with strictly increasing VIDEO timestamps. Complete the optional MediaPipe and
`--pose` preparation above, then configure:

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
