# dori_perception_camera

## Depth camera topic policy

`src/depth_camera_node.cpp` follows the same rule as Python implementation:

- Node code publishes to **relative topics** (`color/image_raw`, `depth/image_raw`, `color/camera_info`, `depth/camera_info`, `depth/scale`) using parameters.
- Launch (`dori_bringup/launch/perception.launch.py`) injects namespace/remappings to canonical app topics under `...`.

This keeps Python/C++ depth camera implementations topic-compatible and prevents hardcoded absolute topic drift.
