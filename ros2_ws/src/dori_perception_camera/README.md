# dori_perception_camera

`rgb_camera_node` captures an independent USB/V4L2 RGB camera. The production
profile launches front and rear instances. No RealSense SDK or depth stream is
required. LiDAR and IMU continue to own navigation measurements.

For an existing RGBD checkout, use `scripts/build.sh --clean` from the repository
root when migrating. It archives the old build/install trees under `.state`
before rebuilding, removing retired installed depth-camera executables.

## Device configuration

Copy `dori_bringup/config/robot.example.yaml` to `.state/robot.yaml`. Set
`front_device` and `rear_device` to distinct capture endpoints under
`/dev/v4l/by-id/` (or `/dev/v4l/by-path/` when identical cameras have no serial).
Use `v4l2-ctl --list-devices` and `v4l2-ctl -d DEVICE --list-formats-ext` to select
actual image endpoints and a supported `camera_pixel_format`, resolution and FPS.
The `/dev/video0` and `/dev/video2` defaults are bench placeholders, not stable
production identities. A metadata endpoint is not a second camera.

Default capture requests: MJPG, 640×480, 15 FPS. The driver publishes the actual
image dimensions returned by the device. Check achieved FPS and simultaneous
USB bandwidth on the robot before deployment. Both camera and person streams
are required by production readiness; desktop tests may disable the rear camera.
A missing device or repeated read failure exits nonzero. Missing/stale frames
never count as ready. Frames use host receipt timestamps, not hardware exposure
timestamps; the cameras are not a synchronized stereo pair.

## Calibration and topics

Set `front_calibration_file` and `rear_calibration_file` to separate ROS
`camera_calibration` YAML files. Relative paths in the deployment YAML resolve
beside that YAML. Supported distortion models: `plumb_bob` (5 coefficients),
`rational_polynomial` (8), `equidistant` (4, fisheye). Calibrate each lens at the
actual capture resolution and final focus. Incorrect files or resolution
mismatches fail instead of publishing incorrect geometry.

Each instance publishes **raw, distorted** BGR8 `color/image_raw` and matching
`color/camera_info`, relative to `/dori/camera/front` or `/dori/camera/rear`.
Image and CameraInfo share a stamp and the distinct optical frame
`camera_front_optical_frame` or `camera_rear_optical_frame`.
An empty calibration path publishes ROS uncalibrated CameraInfo (`K=0`). RGB
inference remains available; calibrated rays are unavailable. No depth, scale,
metric person range, stereo reconstruction or fabricated mounting TF is emitted.
Measure the actual mounts before adding camera-to-body/LiDAR transforms.

Landmark direction calculations account for lens distortion. Person detection
runs on raw images; benchmark edge-of-frame detections on the chosen lenses.
If rectification is added later, expose it as a separate rectified stream with
matching CameraInfo rather than changing the meaning of `image_raw`.

## Validation

`ctest --test-dir ros2_ws/build/dori_perception_camera --output-on-failure`
checks calibration parsing, frame metadata and resolution mismatch rejection.
Physical acceptance still requires two simultaneous camera streams, hot-unplug,
lighting/motion/edge-of-frame trials, stable device identities after reboot, and
Android Chrome/iPhone Safari phone interaction including disconnect while guiding.
